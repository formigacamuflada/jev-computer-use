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

Uma sexta, e a mais cara de todas: **anunciar `done` sem verificar.** O passo
8 do SKILL.md — reobservar e conferir a pós-condição — existia só como
comentário no `loop.py`, e a linha seguinte retornava `done`. O Driver responde
`effect: "unverifiable"`: ele entrega a ação e **não promete** que surtiu
efeito. Numa sessão em `-Executar`, o usuário viu que só três de treze cliques
aconteceram de verdade — o resto foi relatado como `done`. Hoje o loop
reobserva, compara `Observation.signature()` e devolve o desfecho
`unverified` quando a tela não mudou.

Uma quinta, de outra natureza: **tratar recusa como sucesso.** O Cua Driver
recusa uma ação sem marcar `isError` — a recusa vem em
`structuredContent` em **três formas diferentes**, todas já vistas: o objeto
`refusal`, o `status == "refused"`, e — sozinho, sem os outros dois — o
`effect == "refused"`. Checar só uma delas deixa recusa passar por sucesso.
Hoje `raise_if_refused` cobre as três e sobe a mensagem inteira, que é o
diagnóstico.

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
- **A fala era o maior custo escondido do ciclo.** Bloqueante e fora de toda
  métrica: "Feito." custava 2.083 ms e ler a descrição do candidato junto
  custava 5.851 ms. Hoje a fala é `Popen` (19 ms de bloqueio) e só sai nos
  desfechos em que a tela **não** mudou — `escalate`, `error`, `abstained`,
  `exhausted`. Em sucesso o silêncio é a resposta certa: a tela já mudou.
- **Whisper `tiny` não serve para pt-BR**: 0 de 5 acertos. `small` é o padrão.
- **CUDA não funciona aqui**: falta `cublas64_12.dll`. Detectar isso custa
  109 ms; tentar construir na GPU custa 23 s antes de falhar. CPU int8
  transcreve 3 s de áudio em ~145 ms — a GPU não faria diferença.
- **O clique vai por `element_token`, nunca por `element_index` cru.** O token
  é `snapshot:índice` e carrega os dois. Índice sozinho é recusado com
  `snapshot_id_required`; com índice é obrigatório mandar o `snapshot_id`
  junto. Vale igual para `click` e `type_text`.
- **`effect: "unverifiable"` é a resposta normal de um clique bem-sucedido.**
  Não é erro nem promessa: o Driver entregou pela rota de acessibilidade e não
  sabe dizer se o app reagiu. Só a reobservação responde isso.
- **Clique em app Qt costuma não fazer nada.** Medido no qBittorrent: `Button`
  com `invoke` funciona; `MenuItem` (precisa de `expand`) e `TreeItem`/
  `ListItem` (precisam de `select`) recebem o invoke e ignoram. O campo
  `actions` de cada elemento diz o que ele aceita, e o projeto **ainda não usa
  esse campo** — é a próxima correção óbvia.
- **`delivery_mode: "foreground"` é recusado** quando o elemento está fora da
  área visível: *"resolves to (0,0) but is not visibly actionable"*. A saída
  que o Driver sugere é aumentar a janela ou rolar a região até o elemento.
- **Janela minimizada não aceita clique.** O Driver recusa com
  `window_minimized` e diz o que fazer: `bring_to_front` e re-observar. O
  projeto não faz isso sozinho — roubaria o foco, que é justamente o que o
  `delivery_mode: background` existe para evitar.
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

Em ordem de valor, medida em uso real:

1. **Usar o campo `actions` de cada elemento.** É a correção que faz o agente
   funcionar de verdade. Hoje o projeto manda `invoke` em tudo: `Button`
   obedece, mas `MenuItem` precisa de `expand` e `TreeItem`/`ListItem` precisam
   de `select`, e esses simplesmente ignoram. Numa sessão em `-Executar`, só
   três de treze cliques aconteceram. Verificado depois: quatro cliques
   seguidos em `Button` (Geral, Velocidade, Conteúdo) mudaram a tela em todos.
   Existe `invoke_menu` no Driver para o caso dos menus.

2. **Push-to-talk.** Ideia do usuário, e os números dão razão: numa sessão real
   a voz foi **58% do tempo total**, mediana de 7,6 s por comando, porque grava
   até detectar 1,2 s de silêncio. Com tecla, dura o que você segura. Resolve
   também o problema de conversa ambiente virar comando — `"ah, esqueci minhas
   ferramentas, acho que deixei tudo em casa"` clicou em Ferramentas em modo
   real. Mudar a entrada é mais eficaz que melhorar o julgamento.

3. **UI.** Não começada. `run.timing()` e `choice.usage` já saem estruturados
   para isso. O usuário quer: indicador ao apertar a tecla, barra com o que foi
   falado, e os medidores.

Menores:

- **Janela do qBittorrent sumindo da barra de tarefas** durante uma sessão.
  Investigado parcialmente: **não** é o cursor de agente (fica `position: None`,
  ocioso — os cliques vão pela rota de acessibilidade e não movem cursor) e o
  `window_id` não muda. Suspeita atual: o app está configurado para minimizar
  para a bandeja, e o que o usuário viu foram os cliques em Minimizar/Restaurar
  do próprio agente. **Não confirmado.**
- `window_id` obsoleto depois de minimizar/restaurar derruba a observação com
  `No window with window_id N exists`. Falta re-listar janelas quando isso
  acontece.
- Modelo `base` do whisper não testado em pt-BR; seria meio-termo entre o
  `tiny` (ruim) e o `small` (~10 s de carga por sessão).
- `'clique em sem etiqueta'` escala a ~70% por ambiguidade real com o checkbox
  "Etiquetas" na mesma tela.
- Pular a caminhada da árvore quando o app é UWP (ela devolve zero e custa 4 s).
