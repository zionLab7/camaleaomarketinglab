# Seu site e blog

O exportador gera páginas HTML estáticas em `/blog/`, com nome da marca, cores, CTA, fontes, canonical, metadados sociais e BlogPosting JSON-LD. Não depende de WordPress ou banco no site público. O logo selecionado em Marca é exportado como ativo público do blog; os demais elementos da biblioteca permanecem privados.

## Publicar por SSH

Requer acesso SSH à hospedagem, Python 3 no servidor remoto e permissão de escrita na pasta do site. O guia assume site/blog no mesmo domínio, com `/blog/` disponível. Não é um instalador universal de plugins de CMS.

1. Defina website e CTA reais em Marca. Faça backup do site. Reserve `/blog/` para esta aplicação; se já existe blog, revise migração antes de habilitar.
2. No console **publisher**, usuário `cml`, execute:

```bash
ssh-keygen -t ed25519 -f /home/cml/.ssh/id_ed25519 -N '' -C camaleao-blog-publisher
cat /home/cml/.ssh/id_ed25519.pub
```

3. Cadastre **somente a chave pública** no usuário autorizado da hospedagem. Restrinja esse usuário à pasta necessária quando o provedor permitir. Nunca cole a privada no painel ou Git.
4. Obtenha a impressão digital do host em um canal confiável do provedor. `ssh-keyscan -p PORTA HOST` pode coletar a candidata; compare a impressão digital independentemente **antes** de gravar em `/home/cml/.ssh/known_hosts`. Não use StrictHostKeyChecking=no.
5. Configure as variáveis da stack: `CML_BLOG_SSH_HOST`, `CML_BLOG_SSH_PORT`, `CML_BLOG_SSH_USER`, `CML_BLOG_REMOTE_BLOG_DIR=/caminho/absoluto/public_html/blog`. Caminho absoluto sem espaços; pasta final deve ser `blog`.
6. Confirme acesso por SSH com BatchMode e host checking. Ative `CML_BLOG_PUBLISH_ENABLED=true` e recrie o publisher preservando os volumes.
7. Aprove um artigo piloto e confira `/blog/`, artigo, links e sitemap depois do horário reservado.

O upload preserva os arquivos anteriores em backup privado na hospedagem e confirma SHA-256. Publica apenas arquivos próprios do blog; **não substitui o sitemap raiz nem a LP**. Se existe redirecionamento global de todas as rotas para a landing page, crie uma exceção para `/blog/` nas regras do seu servidor/CMS. O `.htaccess` exportado serve para Apache; em Nginx configure rotas e cache de estáticos na hospedagem.

Adicione um link Blog na navegação do seu site e indique `/blog/sitemap.xml` no robots.txt e Search Console. Se já existe sitemap index, inclua o sitemap do blog nele. Preserve sitemaps de outras partes do site.

## Exportação manual

Em um ambiente configurado com o banco da instalação:

```bash
python blog_builder.py --output /tmp/meu-blog
```

A exportação manual inclui artigos **já publicados** no banco. Artigos aprovados são incluídos pelo publicador ao executar a publicação do ID. Não copie um banco privado para uma pasta web. Use exportação de conteúdo no estúdio para outros CMS; integração REST automática não está incluída.

## Desempenho

HTML e CSS locais, sem fontes remotas, mídia social separada do site e analytics condicionados a consentimento. A velocidade final depende da hospedagem, cache, regras do site e integrações adicionais. Confira a LP e o artigo real após instalar; não trate o template como garantia de nota de PageSpeed.
