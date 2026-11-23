# Integração com Instagram

O núcleo funciona sem integração. Quando configurado, o conector usa somente a **Instagram Graph API oficial** para leitura de mídia pública por hashtag e enriquecimento de um perfil profissional já conhecido. Ele não raspa páginas, não automatiza follows/likes e não coleta sugestões de perfis.

## Documentação conferida

Em 2026-10-09, foi conferida a [coleção oficial da Meta para a Instagram API](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-af579d08-121e-4897-8f45-5fd41ace49df). Ela descreve a API para contas profissionais (Business e Creator), uso de aplicativo Meta e token de usuário; para o fluxo com Facebook Login, também descreve a vinculação entre Página e conta profissional. Os campos e permissões continuam condicionados ao produto, versão da API, tipo de conta e aprovação vigente.

O projeto implementa a rota oficial de descoberta como: `hashtag → mídia pública recente/popular → fila local de revisão`. O trabalho é paginado, limitado por execução e preserva a mídia, legenda, data, link e resposta bruta. Se a API retornar o usuário do autor, o sistema cria/associa o candidato; se não retornar, a mídia fica pendente para associação manual. Isso evita inventar um perfil a partir de um Reel.

Não existe promessa de “todos os perfis” ou “todos os Reels”: a Meta aplica permissões, limites de paginação, cotas, elegibilidade da conta e campos disponíveis. A API também não expõe a lista de perfis sugeridos do Instagram.

Configure apenas credenciais obtidas legitimamente como variáveis de ambiente, nunca no banco ou em arquivos Git:

```powershell
$env:INSTAGRAM_ACCESS_TOKEN = 'token-oficial'
$env:INSTAGRAM_ACCOUNT_ID = 'id-da-conta'
$env:INSTAGRAM_API_VERSION = 'v25.0'
```

A tela **Descoberta oficial** tem um teste de conexão explícito e só executa uma busca quando o usuário aciona o botão. Antes de usar em produção, confirme novamente a documentação oficial da Meta na data da mudança, o tipo de conta, permissões, termos e endpoints autorizados.

## Mensagens

O aplicativo prepara, copia e registra contatos. Ele não tenta enviar uma primeira DM por API. A documentação atual da Meta restringe o envio por API a conversas iniciadas pelo destinatário, portanto a primeira abordagem continua manual pela interface do Instagram. [Referência oficial](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-af579d08-121e-4897-8f45-5fd41ace49df)

Fallback disponível hoje: CSV, cadastro manual, texto colado, URL informada, captura fornecida pelo usuário e registro de relações observadas.
