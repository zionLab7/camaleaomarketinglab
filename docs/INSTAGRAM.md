# Instagram: conexão oficial própria

Esta edição publica posts de imagem, carrosséis e Reels na conta profissional conectada. Não pede nem armazena senha de Instagram.

1. Tenha uma conta Instagram profissional e acesso administrativo autorizado.
2. Crie seu próprio app em [Meta for Developers](https://developers.facebook.com/) e configure **Instagram API with Instagram Login**. Não reutilize app/token de outra instalação.
3. Configure permissões oficiais de acesso básico, publicação de conteúdo e insights (por exemplo `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_insights`, conforme disponibilidade e requisitos atuais da Meta).
4. Em modo de desenvolvimento, cadastre a conta como testadora e aceite o convite no Instagram. Para atender contas externas fora dos papéis do app, cumpra revisão, modo Live e verificações exigidas pela Meta. O projeto não dispensa essas etapas.
5. Conclua a autorização oficial no navegador e obtenha ID numérico da conta e token. Gere/troque por token de longa duração pelo fluxo oficial do seu app; não cole app secret no painel ou em comandos que fiquem no histórico.
6. Em **Conexões → Instagram**, informe ID e token; clique em verificar. Só marque publicação depois de validar conta, permissões, domínio público HTTPS e conteúdo piloto.
7. A renovação automática é **opt-in** para tokens de longa duração compatíveis do Instagram Login. O sistema tenta a renovação oficial após 30 dias, registra expiração quando retornada e exige nova autorização se houver revogação/expiração. Não transforme um token desconhecido em “60 dias” por suposição.
8. Confira os resultados da primeira peça aprovada na própria conta e no registro do painel.

`CML_DOMAIN` precisa ser o domínio público correto do painel: a Meta baixa as mídias por links assinados de curta duração. Não coloque Basic Auth adicional que bloqueie `/public/instagram/` sem oferecer uma exceção equivalente. Não exponha a biblioteca privada toda.

O publicador usa outbox e aprovação vinculada ao conteúdo. Em falha ambígua depois de solicitar publicação, confira a conta antes de repetir: a aplicação interrompe em vez de presumir que o envio falhou. Informações de origem de imagens ficam registradas; os campos de divulgação previstos pela plataforma continuam sendo respeitados quando aplicáveis. O operador responde por direitos de uso e pelo conteúdo que aprova.

Documentação de referência: [Instagram Platform](https://developers.facebook.com/docs/instagram-platform/), [Content Publishing](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing/). As telas/permissões da Meta podem variar; se um requisito não aparecer, confira o produto e a versão Graph configurados (`CML_META_GRAPH_VERSION`). Facebook Login é um caminho distinto; o guia principal desta edição usa Instagram Login.
