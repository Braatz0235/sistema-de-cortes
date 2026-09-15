# Sistema de Cortes

Suba um vídeo, o sistema transcreve a fala, identifica os melhores momentos
(trechos com maior potencial de engajamento) e gera cortes prontos — você
escolhe, para cada corte, em qual formato/plataforma ele deve sair
(TikTok, Instagram Reels, YouTube Shorts, Instagram Feed, Facebook, YouTube,
X/Twitter, LinkedIn ou o formato original).

## Como funciona

1. **Upload** — o vídeo é salvo em `storage/videos/<id>/source.<ext>`.
2. **Análise** (processo em segundo plano):
   - `ffprobe` extrai duração/resolução.
   - `ffmpeg` extrai o áudio.
   - A fala é transcrita com timestamps por palavra — por padrão usando
     `faster-whisper` localmente (grátis, mas baixa um modelo na primeira
     vez); **se `OPENAI_API_KEY` estiver configurada**, usa a API de
     transcrição da OpenAI (Whisper) na nuvem em vez disso, sem precisar
     baixar nada.
   - A transcrição é enviada para o Claude (Anthropic), que devolve os
     melhores trechos (início/fim, título, resumo, score, plataformas
     sugeridas, hashtags). **Sem `ANTHROPIC_API_KEY` configurada**, um
     heurístico local (palavras-chave, pontuação, densidade de números)
     assume o lugar automaticamente — o sistema nunca trava por falta da
     chave.
3. **Revisão** — a interface mostra os cortes sugeridos com prévia
   (reproduz só aquele trecho do vídeo original).
4. **Exportação** — para cada corte, você marca uma ou mais
   plataformas/formatos e clica em "Gerar". Cada exportação roda em um
   único passo de `ffmpeg` que corta o trecho, reformata para
   vertical (9:16) / quadrado (1:1) / horizontal (16:9) — preenchendo os
   espaços com um fundo desfocado do próprio vídeo em vez de cortar
   pessoas/texto para fora do quadro — e, se ativado, queima a legenda
   (gerada a partir dos timestamps por palavra) no vídeo.

## Estrutura

```
Dockerfile / docker-compose.yml / .env.example   # deploy com um comando
backend/
  app/
    main.py              # app FastAPI + serve o frontend estático
    config.py             # variáveis de ambiente
    models.py              # schemas (VideoJob, Clip, Export, presets de plataforma)
    storage.py             # persistência em JSON por vídeo (sem banco de dados)
    jobs.py                 # orquestração em thread pool: análise e exportação
    api/
      videos.py               # rotas HTTP (upload, cortes, exportação, download)
      health.py                # GET /api/health (ffmpeg disponível? IA ou heurístico?)
    pipeline/
      ffmpeg_utils.py         # probe, corte, reformatação, filtro de legenda
      captions.py               # geração de legendas .ass a partir dos timestamps
      transcribe.py              # faster-whisper
      highlight_detection.py      # Claude + heurístico de fallback
  tests/                          # pytest (não depende de ffmpeg/whisper/Claude reais)
frontend/
  index.html / styles.css / app.js   # SPA simples, sem build step
storage/videos/                        # dados de runtime (gitignored)
```

## Rodando com Docker (recomendado)

Pré-requisito: Docker + Docker Compose.

```bash
cp .env.example .env
# edite o .env se quiser usar o Claude (ANTHROPIC_API_KEY) ou trocar o
# tamanho do modelo de transcrição — nenhum dos dois é obrigatório

docker compose up --build
```

Abra `http://localhost:8000`. Os vídeos ficam em `./storage/videos` no host
(persistem entre reinícios) e o modelo do `faster-whisper` fica num volume
Docker próprio, baixado só na primeira vez que um vídeo é processado.

> Não foi possível rodar um `docker build` de ponta a ponta durante o
> desenvolvimento porque este ambiente de sandbox bloqueia o download de
> imagens do Docker Hub por política de rede — o `Dockerfile` foi revisado
> manualmente linha a linha (os caminhos batem com `config.py`/`main.py`,
> que já foram testados de verdade). Rode `docker compose up --build` e,
> se algo não bater, me avise.

## Rodando sem Docker

Pré-requisitos: Python 3.11+, `ffmpeg`/`ffprobe` no PATH.

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# opcional: usar o Claude para escolher os cortes (senão usa o heurístico local)
export ANTHROPIC_API_KEY=sk-ant-...

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abra `http://localhost:8000` — o próprio FastAPI serve o frontend.

### Verificando se está tudo certo

```bash
curl http://localhost:8000/api/health
```

Retorna se o `ffmpeg` foi encontrado e se a seleção de cortes está usando
Claude ou o heurístico local. O upload de vídeo é recusado (erro 503) se o
`ffmpeg` não estiver disponível, e qualquer arquivo que não seja um vídeo
válido é rejeitado no próprio upload (o servidor roda `ffprobe` nele antes
de aceitar).

### Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `STORAGE_DIR` | `storage/videos` | onde os vídeos/metadados/exportações ficam salvos |
| `WHISPER_MODEL_SIZE` | `base` | tamanho do modelo faster-whisper (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `WHISPER_DEVICE` | `cpu` | `cpu` ou `cuda` |
| `WHISPER_COMPUTE_TYPE` | `int8` | precisão do faster-whisper |
| `OPENAI_API_KEY` | — | ativa a transcrição via API da OpenAI; sem ela, usa o `faster-whisper` local |
| `OPENAI_STT_MODEL` | `whisper-1` | modelo usado na API de transcrição da OpenAI |
| `ANTHROPIC_API_KEY` | — | ativa a seleção de cortes por IA; sem ela, usa o heurístico local |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | modelo usado para escolher os cortes |
| `MIN_CLIP_SECONDS` / `MAX_CLIP_SECONDS` | `15` / `90` | duração alvo de cada corte |
| `MAX_CLIPS` | `8` | número máximo de cortes sugeridos por vídeo |
| `MAX_UPLOAD_BYTES` | 2 GB | tamanho máximo de upload |

Observação: no modo padrão (local), o `faster-whisper` baixa o modelo do
Hugging Face no primeiro uso (fica em cache depois), o que exige internet
nessa primeira execução. Configurando `OPENAI_API_KEY`, não há download
nenhum — a transcrição roda na nuvem via API da OpenAI.

## Testes

```bash
cd backend
source .venv/bin/activate
pytest
```

Os testes cobrem a construção dos comandos `ffmpeg`, a geração/segmentação
de legendas, o heurístico de detecção de destaques (e o parsing da resposta
do Claude, via mock) e as rotas da API (upload, listagem, exportação,
validações) — tudo sem precisar rodar `ffmpeg`, `whisper` ou chamar a API
da Anthropic de verdade.

## Limitações conhecidas / próximos passos

- O "smart crop" usa um fundo desfocado centralizado em vez de rastreamento
  de rosto — funciona bem para conteúdo já centralizado (talking head), mas
  não recentraliza automaticamente quando o assunto se move muito na tela.
- A legenda queimada é gerada em blocos de poucas palavras (sem destaque
  palavra-a-palavra estilo karaokê).
- Não há autenticação/multiusuário — pensado para uso pessoal/local.
