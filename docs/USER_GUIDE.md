# Guia de uso

## Fluxo diário

1. Quando a conta Meta estiver configurada, use **Descoberta oficial** para buscar mídia pública por hashtag, por exemplo `maesolteira`. Escolha somente Reels e o limite da execução.
2. Revise a fila da execução. Quando a API retornar o usuário autor, o candidato é associado automaticamente; quando não retornar, abra a mídia, confirme o usuário e associe-o pelo campo da fila.
3. Cadastre um candidato ou importe um CSV em **Importação/exportação** quando a fonte for externa ou manual.
4. Registre a bio, contagem de seguidores, URL ou captura disponível em **Evidências e Links**. Sempre indique a origem real.
5. Associe candidatos a um perfil-semente em **Perfis-semente** quando a relação foi observada ou importada.
6. Revise cada candidato na **Fila de revisão**. Aprovar e rejeitar alimentam o histórico local; **Não contatar** bloqueia novas mensagens.
7. Após acumular pelo menos 8 decisões, incluindo 3 aprovações e 3 rejeições, treine o modelo em **Aprendizado**. A pontuação apenas ordena a fila.
8. Em **Mensagens**, escolha um modelo, confira o texto, copie-o e conclua o contato pelo meio permitido. Depois registre manualmente o que ocorreu.

## Estados e evidências

- **Confirmado**: veio de fonte conectada autorizada ou revisão humana com evidência suficiente.
- **Inferido**: é uma classificação ou sugestão e não um fato.
- **Pendente**: faltam dados ou revisão.
- **Desatualizado**: dado registrado, mas antigo.
- **Não verificável**: a fonte não permitiu confirmação.

Uma captura de Story é identificada como fornecida pelo usuário. O aplicativo nunca afirma tê-la acessado sozinho.

## Opt-out

Registre `opt-out` ou `Não contatar` imediatamente. Esse estado impede preparar e registrar novos contatos. Não o remova sem revisar o caso e a evidência.
