# Privacidade e segurança

Os dados ficam localmente em SQLite, com evidências, exportações, backups, modelos e logs em subpastas da pasta de dados. Proteja a conta do Windows e os backups, pois a base pode conter dados pessoais e comerciais.

- senhas, cookies e tokens não são salvos no SQLite ou nos logs;
- dados não são enviados a LLMs ou serviços externos por padrão;
- URL só é acessada por ação explícita, com timeout, limite de bytes/redirecionamentos e bloqueio de rede interna;
- arquivos aceitos têm extensão e tamanho limitados e são salvos em caminhos controlados;
- exportação CSV prefixa células que poderiam ser fórmulas;
- rascunho de mensagem não é envio; o estado enviado é registrado apenas após ação manual do usuário.

Para excluir dados da operação, abra o candidato em **Candidatos > Detalhes** e confirme **Arquivar candidato**. O registro deixa de aparecer nas filas, mas o histórico é preservado e pode ser restaurado em **Configurações > Candidatos arquivados**. Faça exportação ou backup antes de uma manutenção definitiva dos arquivos.
