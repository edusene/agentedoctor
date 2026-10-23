# Design e acessibilidade

## Direção

Dois públicos: o **paciente**, que só vê o WhatsApp (texto curto, em português, sem jargão; o doutor pediu menos texto), e a **equipe**, que usa o painel web em desktop e, às vezes, no celular. O painel é utilitário: listas, filas e uma agenda. Não há marca visual definida além do logo do consultório.

## Sistema existente

Sem framework de UI e sem build: `templates/index.html`, `templates/login.html`, `static/style.css` e `static/app.js` (JS puro). `static/style.css` é a fonte de verdade de cores e espaçamento; não há tokens documentados separadamente. Estado de conexão do Google usa âmbar quando desconectado (commit `339e3de`).

## Interação

Mensagens do agente: uma ideia por mensagem, pausa entre bolhas configurável (`PAUSA_*`), indicador de digitação. No painel: erros devem aparecer ao lado da ação, operações lentas mostram progresso, e uma falha de API não pode ser silenciosa (a Agenda já falhou em silêncio por um 429 em HTML; hoje o limite é por IP do cliente).

## Revisão

Não há revisão de acessibilidade do painel registrada (teclado, foco visível, contraste, rótulos de campo): é uma lacuna conhecida, listada em `docs/setup.md`. O critério visual não se aplica ao canal WhatsApp.

## Manutenção

Mudança de interface atualiza `static/style.css` e este arquivo quando uma regra mudar.
