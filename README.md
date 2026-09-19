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

## Voz (pt-BR)

O lançador cria o venv do projeto e instala as dependências na primeira
execução. Não use `pip install` no Python do sistema: esta máquina tem mais de
um Python no PATH (`C:\Python314` e `...\Local\Python\pythoncore-3.14-64`) e
qual deles responde por `python` muda conforme o shell — instalar num e rodar
no outro dá `ModuleNotFoundError: No module named 'winrt'`.

```powershell
.\scriptsoz.ps1                       # qBittorrent, dry-run (não clica)
.\scriptsoz.ps1 -App Discord
.\scriptsoz.ps1 -Texto                # digitado, para desenvolver
.\scriptsoz.ps1 -App chrome -Executar  # sai do dry-run: clica de verdade
```

O lançador resolve o binário, sobe o daemon se estiver parado e ajusta o
`PYTHONPATH`. Use PowerShell — `set VAR=x && cmd` é sintaxe de `cmd.exe` e não
funciona no PowerShell 5.1.

**O vocabulário sai da tela.** O reconhecimento offline do Windows exige uma
lista fechada de frases — o que parece limitação, mas casa com a arquitetura:
o espaço de ações já é fechado. A cada volta do loop o agente observa a janela,
gera `verbo × rótulo` para cada elemento acionável e recompila a gramática.
Vocabulário fechado também eleva muito a acurácia: o motor escolhe entre N
frases conhecidas em vez de transcrever português aberto.

Medido no qBittorrent ao vivo: **321 elementos → 290 frases, compiladas em 238 ms.**
O casamento tolera o que a tela mostra a mais — falar `"baixando"` acerta o
rótulo `"Baixando (0)"`.

### O que foi verificado e o que não

| | |
|---|---|
| Criar recognizer pt-BR | ✅ de processo Python desktop não empacotado |
| Compilar gramática offline | ✅ `SpeechRecognitionResultStatus.SUCCESS` |
| Gramática de tela real | ✅ 290 frases em 238 ms |
| Casamento fala → rótulo | ✅ coberto por teste |
| **Reconhecer voz humana** | ⬜ **não testado — exige alguém falando** |

### Armadilhas do motor de fala

**Feche o recognizer antes de criar outro.** Ele segura o dispositivo de
captura; um segundo com o primeiro vivo falha com `0x800455A0 Internal Speech
Error`. Isso acontece sempre que o vocabulário muda entre uma escuta e outra —
ou seja, o tempo todo.

**Um event loop para a sessão inteira.** `asyncio.run` por escuta deixa o
recognizer preso a um loop já fechado na chamada seguinte.

**Contadores na UI envenenam a gramática.** O qBittorrent mostra
`"Semeando (12)"` e o número muda a cada segundo. Se entrar no vocabulário,
cada observação gera uma gramática diferente, o recognizer é recriado sem
parar e o motor quebra. `normalizar()` remove contadores entre parênteses —
o que também deixa a frase mais natural, já que ninguém fala "semeando doze".

### Notas de plataforma

`winsdk` **não serve**: sem wheel para Python 3.14 e exige Visual Studio para
compilar (esta máquina só tem TDM-GCC). Os pacotes `winrt-*` por namespace têm
wheel cp314 e funcionam.

`System.Speech` também não serve — nenhum recognizer instalado nesta máquina.

O **ditado online está desligado** (a política de fala online nunca foi aceita),
então o modo nuvem está fora. Só o modo gramática offline funciona — que é o
que queremos de qualquer forma, por privacidade e latência.

PowerShell não consegue hospedar isto: `SpeechRecognizer.Constraints` volta como
`System.__ComObject` sem o método `Add` projetado. Limitação da projeção WinRT
do PowerShell para `IVector<T>`, não do motor.

## Cua Driver

```powershell
irm https://cua.ai/driver/install.ps1 | iex
cua-driver autostart kick      # sobe o daemon sem precisar relogar
```

```bash
set PYTHONPATH=src
python -m jevcu --driver cua --app qbittorrent --show-table
python -m jevcu --driver cua --app qbittorrent --dry-run clicar em Semeando
```

A CLI recebe os argumentos como um unico JSON posicional
(`cua-driver call <tool> '{...}'`), e o alvo de uma acao e
`pid` + `window_id` + `element_index` do snapshot corrente.
As acoes usam `delivery_mode: background`, que nao rouba o foco -- o contrato
do Driver trata isso como primeira tentativa obrigatoria, nao como sugestao.

### Loop completo contra o qBittorrent ao vivo

```
elementos           : 321
arvore inteira      : 6186 tokens
esqueleto enviado   : 1785 tokens (profundidade 8)
reducao             : 71.1%
acao produzida      : click {pid, window_id, element_index: 18,
                             delivery_mode: background}
```

## Serialização da árvore de UI

`tree.py` compacta a árvore antes de mandar pro Jev: visão rasa, ramos densos
truncados com `children_count` e uma alça `drill`, e nós estruturais anônimos
(`Pane`/`Group` sem nome) atravessados sem consumir profundidade.
`fit(root, budget_tokens=N)` devolve o maior esqueleto que cabe no orçamento.

`uia.py` + `scripts/uia_tree.ps1` leem a árvore real do Windows via UI Automation,
sem instalar nada. É ponte até o Cua Driver — `UiaDriver` é **somente leitura**:
`execute()` falha de propósito em vez de fingir que agiu.

### Medições em janelas reais (via Cua Driver)

```
app           elems   árvore   esqueleto   prof x larg
Discord         742    10694        3356      3 x 200   (Electron)
WhatsApp        220     5094        5094      6 x 100   (cabe inteira)
qbittorrent     321     6187        5790     20 x 100
Configurações     0        0           0        —       (UWP: opaco)
```

Orçamento de 6000 tokens; o limite de state do Jev é 32k. Nenhuma janela real
desta máquina chega perto do teto — a maior árvore inteira deu 10694 tokens.

**`fit()` ajusta profundidade E largura.** A primeira versão só variava
profundidade e desperdiçava o orçamento: o Discord ficava em 256 tokens de
6000 disponíveis. A causa é a forma da árvore — `Document` → um único
`Group "app-mount"` com **451 filhos diretos**. Árvore rasa e larguíssima, onde
mexer na profundidade não muda nada. Corrigido, o mesmo Discord entrega 3356
tokens de informação útil dentro do mesmo orçamento.

A lição que virou teste de regressão: **redução alta não é sucesso.** Cortar
abaixo do orçamento é perda de informação, não economia.

### Limitações confirmadas com o Cua Driver

**Conteúdo web:** UIA puro via PowerShell não ativa a acessibilidade completa
do Chromium e devolve só a casca do navegador (79 nós). O Cua Driver ativa, e a
mesma classe de janela passa a entregar 220-742 elementos com o conteúdo da
página. Para interagir, as ferramentas `browser_*` via CDP são o caminho certo;
UIA serve para ler.

**Apps UWP são opacos.** `SystemSettings` e `ApplicationFrameHost` devolvem
**0 elementos até pelo Cua Driver**, testados pelos dois pids. Não é limitação
da ponte em PowerShell. Configurações do Windows, Mail e afins ficam fora do
alcance semântico; para eles só resta o caminho visual.

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
