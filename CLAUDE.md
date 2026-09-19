# jevcu — orientação para uma sessão nova

Computer use por voz no Windows. **Cua Driver** observa a tela e age,
**TypeSafe Jev** decide, **faster-whisper** ouve em pt-BR.

O usuário **não é programador**. Explique decisões em português, sem jargão
desnecessário, e prefira medir a supor.

## Rodar

```powershell
.\scripts\voz.ps1 -Whisper -Jev      # voz + Jev real, dry-run
.\scripts\voz.ps1 -Texto             # digitado, para desenvolver
.\scripts\voz.ps1 -Whisper -Jev -Executar   # SAI DO DRY-RUN: clica de verdade
```

O lançador sobe o daemon do Cua sozinho e usa o venv do projeto. Testes:
`.\.venv\Scripts\python.exe -m pytest tests/ -q`

## A regra que não se quebra

Do `skills/jev-use/SKILL.md` do cua:

> *Never let Jev invent tool names, coordinates, refs, targets, delivery modes,
> or other arguments.*

A aplicação monta a tabela de candidatos; o Jev devolve **um ID dela**. Quem
executa é o código.

## Erros já cometidos — não repetir

Todos da mesma família: **pôr na camada determinística uma decisão que cabe ao
juiz.** Aconteceu três vezes.

1. **Rejeitar o que não casava com um rótulo.** Bloqueava linguagem natural
   legítima — "quero ver o que já terminou de baixar" não casa com "Completado"
   por texto nenhum, e era descartada antes do Jev ver. O casamento é **dica**,
   não portão.

2. **Reescrever o objetivo como "clicar em X".** Apagava a frase original, e o
   Jev confirmava qualquer coisa: contar uma história com a palavra "parado"
   virou um clique. Hoje o objetivo é a **frase original** e o rótulo vai como
   dica em `observation["speech"]`. Medido: reescrito 99%, frase original 40%.

3. **Casar por substring.** "parado" está dentro de "separado". Hoje exige
   sequência inteira de palavras.

Um quarto padrão, de outra família: **duas descrições iguais na tabela são a
mesma pergunta feita duas vezes.** O Jev não responde 50/50 a um empate exato
— desempata pela primeira chave e ainda relata confiança alta. O loop lia isso
como certeza. Hoje `build_candidates` descarta descrição repetida.

Outro padrão: **redução alta não é sucesso.** O `fit()` cortava o Discord para
256 tokens de um orçamento de 6000 — isso é perda de informação, não economia.

## Fatos medidos (não re-descobrir)

- **Estimador de tokens**: 1,7 caractere por token, calibrado contra o `usage`
  real. A régua de 4 caracteres errava por 2,4×.
- **O campo `confidence` da API não serve de limiar.** É corrigido pelo acaso,
  então encolhe quando a tabela de candidatos cresce: o mesmo acerto óbvio
  recebe números diferentes conforme a tela tem 8 ou 24 elementos. A régua do
  projeto é `margin_confidence` — o quanto o primeiro se destacou do segundo —
  e vale igual no mock e no live. O número do provider fica em
  `choice.provider_confidence`, só para diagnóstico.
- **Whisper `tiny` não serve para pt-BR**: 0 de 5 acertos. `small` é o padrão.
- **CUDA não funciona aqui**: falta `cublas64_12.dll`. Detectar isso custa
  109 ms; tentar construir na GPU custa 23 s antes de falhar. CPU int8
  transcreve 3 s de áudio em ~145 ms — a GPU não faria diferença.
- **Apps UWP devolvem 0 elementos** pela árvore de acessibilidade, inclusive
  pelo Cua Driver. O contorno é o OCR: medido nas Configurações do Windows,
  0 elementos viram 52 linhas de texto e 24 candidatos clicáveis, com acentos
  corretos. O clique é por pixel, e funciona porque o `click` do Driver em
  `delivery_mode: background` faz hit-test de UIA no ponto antes de recorrer
  ao PostMessage — ele acha o controle que a caminhada da árvore não enxergou.
- **Custo de uma observação com OCR** (janela 1200x932): `list_windows` 2,0 s,
  caminhada da árvore 4,0 s, captura 2,2 s, OCR 0,65 s. O OCR é a etapa mais
  barata. A cara é a árvore que devolve zero em UWP — pular essa caminhada
  quando o app é UWP é a otimização óbvia e ainda não foi feita.
- **Backend `winrt` de voz**: funciona isolado, falha na sessão do usuário com
  `0x800455A0`. Nunca reproduzido. Use `whisper`.
- **A rede do usuário é instável.** Timeouts do Jev são comuns; o cliente já
  tem retry com timeout curto. Não confunda com bug.

## Layout

```
src/jevcu/
  contracts.py    Candidate, Choice, Usage, validate_choice (falha fechado)
  candidates.py   tabela a partir da observação; `must_include` reserva o alvo
  ocr.py          OCR nativo do Windows; é o que salva as telas UWP
  jev.py          cliente HTTP; backends mock e live; mede latência e tokens
  driver.py       CuaDriver (age), UiaDriver (só lê), MockDriver (testes)
  loop.py         os 8 passos do SKILL.md; tempo por etapa
  tree.py         esqueleto e drill-down; `fit()` busca profundidade × largura
  voice/          grammar (vocabulário da tela), stt, tts pt-BR
```

## Convenções

- Comentários e mensagens de commit em português, explicando **por quê**.
- Commits terminam com `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Segredos ficam em `jev-api-token.txt` e `token.txt` na raiz, **ignorados pelo
  git**. Nunca commitar, nunca imprimir.
- Push usa credential helper temporário; o PAT nunca entra no `.git/config`.
- Toda correção vinda de uso real vira teste de regressão.

## Pendências

- UI (não começada) — os dados já saem estruturados em `run.timing()` e
  `choice.usage` justamente para isso.
- Modelo `base` do whisper não testado em pt-BR; seria meio-termo entre o
  `tiny` (ruim) e o `small` (~10 s de carga por sessão).
- `'clique em sem etiqueta'` escala a ~70% por ambiguidade real com o checkbox
  "Etiquetas" na mesma tela.
