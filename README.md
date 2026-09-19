# jevcu — computer use por voz no Windows

Cua Driver observa e age. TypeSafe Jev decide. A aplicação é dona da tabela de ações.

```
voz (pt-BR) → observação (Cua Driver) → tabela de candidatos → Jev escolhe 1 ID
                                                                      ↓
                          verifica pós-condição ← executa 1 ação ← valida o ID
```

## A regra que não se quebra

Vem do [`skills/jev-use/SKILL.md`](https://github.com/trycua/cua/blob/main/skills/jev-use/SKILL.md) do cua:

> *Never let Jev invent tool names, coordinates, refs, targets, delivery modes, or other arguments.*

O Jev recebe apenas: objetivo, observação compacta, histórico e **IDs de candidatos com descrição**.
Ele devolve **um ID**. Quem monta a tabela e executa é o código — em `candidates.py` e `loop.py`.

Por isso o Jev **não precisa de um LLM acima dele** enquanto o espaço de ações for enumerável
a partir da tela. Um LLM (Claude) só entra quando a confiança fica abaixo do limiar.

## Rodar agora (sem credencial, sem instalar nada)

```bash
set PYTHONPATH=src
python -m jevcu --show-table
python -m jevcu --no-speak clicar em Salvar
python -m jevcu --no-speak faz alguma coisa ai     # ambíguo → escala, não age
```

O backend `mock` é determinístico e roda offline. Serve para exercitar o loop inteiro
enquanto a chave do Jev não funciona.

## Estado verificado nesta máquina

| Componente | Status |
|---|---|
| OCR nativo (`Windows.Media.Ocr`) | ✅ en-US + pt-BR, **151 ms** em 1920x1080 |
| TTS (`Microsoft Maria Desktop` pt-BR) | ✅ instalada |
| STT WinRT (`Windows.Media.SpeechRecognition`) | ✅ pt-BR, ditado e gramática offline |
| STT `System.Speech` | ❌ **nenhum recognizer instalado** — por isso o backend é WinRT |
| NPU / Windows AI Foundry `TextRecognizer` | ❌ Ryzen 9800X3D não tem NPU |
| Cua Driver | ⬜ não instalado ainda |
| Chave do Jev | ⚠️ presente mas retorna **401** |

## Instalar o Cua Driver

```powershell
irm https://cua.ai/driver/install.ps1 | iex
```

Depois troque o backend:

```bash
python -m jevcu --driver cli --dry-run abrir o menu Arquivo
```

## Ligar o Jev de verdade

```powershell
$env:TYPESAFE_API_KEY = "..."
python -m jevcu --decide live --dry-run clicar em Salvar
```

Sem a variável, `config.load_typesafe_key()` cai para `jev-api-token.txt` na raiz
(conveniência de desenvolvimento; a raiz está no `.gitignore`).

## Política de confiança

| Faixa | Comportamento |
|---|---|
| `≥ act_threshold` (0.85) | age sozinho |
| entre piso e limiar | **escala** — pergunta antes |
| `< floor_threshold` (0.40) | reobserva; após 3 tentativas sem progresso, escala |

Ajuste por env: `JEVCU_ACT_THRESHOLD`, `JEVCU_FLOOR_THRESHOLD`.

## Layout

```
src/jevcu/
  contracts.py    Candidate, Choice, validate_choice — falha fechado
  candidates.py   monta a tabela a partir da observação (+ reobserve/abstain)
  jev.py          adaptador Jev: HTTP direto, backends mock e live
  driver.py       Cua Driver (CLI) + MockDriver para desenvolver
  loop.py         os 8 passos do SKILL.md
  ocr.py          Windows.Media.Ocr
  voice/tts.py    SAPI pt-BR
  voice/stt.py    text | winrt | whisper
scripts/ocr.ps1   helper WinRT do OCR
tests/            14 testes, rodam offline
```

## Notas de implementação

**OCR via subprocess custa caro.** O OCR em si leva 151 ms, mas abrir um PowerShell por
chamada adiciona ~570 ms. Para um loop quente, troque por binding WinRT direto (`winsdk`)
ou mantenha um processo PowerShell vivo.

**Texto pequeno derruba o OCR nativo.** No teste real ele leu `dicking` em vez de `clicking`
e `leam` em vez de `learn`. Passe recortes ampliados 2×, não a tela inteira. Se precisar de
mais acurácia, RapidOCR (PP-OCRv5 em ONNX) na GPU é o plano B.

**Prefira a árvore de acessibilidade ao OCR.** O UIA dá nome, papel e bounds exatos em
~10-50 ms, sem inferência. OCR é fallback para o que o UIA não expõe; OmniParser é fallback
do fallback (canvas, jogos, remote desktop).

**Inglês nas `instructions`.** A doc do Jev diz que inglês é a língua primária e que outras
têm acurácia menor. O `state` carrega português (é o que está na tela), mas as perguntas e
critérios vão em inglês de propósito.

## Licença a observar

O `cua-perception` (PR #3943, ainda draft) empacota o detector do OmniParser sob
**AGPL-3.0-only**. O Cua Driver padrão continua MIT. Se for distribuir isto fechado,
use o detector **YOLOv9-E (MIT)** que o OmniParser ganhou em julho/2026 — os detectores
antigos, baseados em Ultralytics, é que são AGPL.

## Referências

- [`jev-use` recipe](https://github.com/trycua/cua/tree/main/libs/cua-driver/examples/jev-use) — PR #3916, no main
- [`cua-perception`](https://github.com/trycua/cua/pull/3943) — OmniParser + PP-OCR em Rust, draft
- [RFC do boundary](https://github.com/trycua/cua/pull/3934)
- [Docs do Jev](https://docs.typesafe.ai/api)
