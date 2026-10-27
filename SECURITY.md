# Segurança

Não publique tokens, senhas, JSON de conta de serviço, auth.json, chaves SSH, bancos ou backups em issues. Relate vulnerabilidades de forma privada pelo GitHub Security Advisory do repositório quando disponível; se indisponível, procure o mantenedor sem anexar segredos publicamente.

Esta edição tem um administrador por stack. Exponha apenas o web pelo Traefik/HTTPS. Proteja também Portainer e o host; administradores do Docker podem acessar volumes/credenciais. Não monte o socket Docker na aplicação. Mantenha backups privados e restauração testada.

Credenciais e contatos usam AES-GCM com derivação do segredo mestre. Não mude CML_APP_SECRET em uma instalação com dados sem um procedimento de recriptografia: perderia acesso aos dados. Sessões atuais são assinadas por esse segredo; a troca da senha administrativa não revoga por si só sessões já abertas.

Em incidente: suspenda a publicação/ingestão, restrinja rede, preserve evidências privadas, revogue tokens/chaves no provedor, restaure somente dados conhecidos e faça rotação com migração de credenciais. Não “corrija” vazamento apagando só o arquivo do último commit: revogue o segredo e revise o histórico.

O revisor de IA não substitui aprovação humana, validação comercial ou avaliação de segurança. RSS e fontes são não confiáveis; downloads bloqueiam IPs privados, redirecionamentos e respostas acima do limite. Uploads de usuário aceitam somente raster validado; templates não executam HTML do modelo. O código contém um servidor HTTP mínimo; use limites de requisição/conexão no proxy e não o exponha diretamente à internet.
