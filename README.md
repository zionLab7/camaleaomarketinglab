# Camaleão Marketing Lab

**Sua marca. Sua equipe de marketing com IA. Seu servidor.**

Orquestrador de conteúdo, aprovação, publicação e aprendizagem comercial, personalizável por negócio e hospedado com Docker, Portainer e Traefik. Interface em português. Conteúdo orientado pelo idioma, público, identidade e metas da instalação.

> Uma instalação por empresa, com um administrador. Não é uma plataforma SaaS com isolamento de vários clientes no mesmo banco. Para vários negócios, use stacks, domínios e volumes separados.

## O que está incluído

- Dashboard executivo, radar RSS de tendências e concorrentes e registro auditável.
- Marca configurável no painel: público, fatos, tom, pilares, metas, logo, cores, CTA e preferências por agente.
- Equipe especializada com LangGraph: análise → estratégia → pesquisa → copy → SEO → arte/motion → renderização → revisão. Checkpoints, retomada e até duas rodadas de revisão.
- Posts, carrosséis e Reels com templates controlados; biblioteca privada com upload de imagens autorizadas. Três vetores abstratos originais acompanham a instalação; fotos, clientes e materiais de outras empresas não acompanham.
- Calendário Instagram/blog com 1 a 6 publicações por dia em cada canal, intervalo mínimo configurável e seis dias de propostas à frente. Sem aprovação humana, não publica.
- Instagram profissional via API oficial, com aprovação vinculada ao hash da mídia e controle de envio para reduzir duplicatas.
- Blog estático rápido em `/blog/`, SEO básico, referências, sitemap próprio e CTA para seu site/LP. Publicador SSH com host fixado, backup e conferência de hashes.
- Medição consentida pelo GTM/GA4, relatórios de GA4 e Search Console, leads via n8n/webhook e status em uma planilha privada.
- Métricas agregadas orientam agentes sem repassar contatos ou observações privadas. Relatório HTML e envio semanal por SMTP opcional.

**Canais automáticos implementados:** Instagram e blog estático por SSH. Os outros canais que aparecem no estúdio servem para planejamento/exportação manual. Não há integração automática com Facebook, TikTok, LinkedIn, WordPress REST ou campanhas de anúncios nesta versão.

## Começar em dez minutos: teste local

Requer Docker Compose v2 e Python 3 para gerar o arquivo privado de configuração.

```bash
git clone https://github.com/zionLab7/camaleaomarketinglab.git
cd camaleaomarketinglab
python3 scripts/generate_env.py
docker compose up -d --build
```

Abra **http://localhost:8080**. Usuário: `admin`. A senha aleatória está em `CML_ADMIN_PASSWORD` no `.env` local (não compartilhe esse arquivo). O sistema inicia vazio e sem conexões externas. Os executores ficam ativos, mas geração e publicação exigem configuração explícita.

1. Em **Marca e agentes**, preencha seu negócio, website/CTA reais, fontes editoriais e preferências. Nunca use `example.com` em produção.
2. Adicione logo/imagens autorizadas; use o ID do logo no campo correspondente.
3. Siga o [primeiro acesso](docs/PRIMEIRO-ACESSO.md) e conecte os serviços desejados.
4. Envie um briefing e confira texto, imagens, fatos e data antes de aprovar.

## Implantar pelo Git no Portainer

Use [`compose.portainer.yml`](compose.portainer.yml), com imagem publicada pelo workflow do GitHub em `ghcr.io/zionlab7/camaleaomarketinglab:main`.

**Guia completo:** [Docker, Portainer e Traefik](docs/DEPLOY.md). Inclui variáveis, DNS, rede, HTTPS, atualização, backup e retorno à versão anterior. O stack é para **Docker Standalone**. Swarm exige uma adaptação própria; não use o arquivo sem revisão.

## Integrações, passo a passo

| Conexão | Guia | Condição |
| --- | --- | --- |
| Codex / OpenAI | [IA e autenticação](docs/IA.md) | Assinatura compatível e limites disponíveis; API opcional cobrada à parte |
| Instagram | [Conta profissional e token Meta](docs/INSTAGRAM.md) | App e permissões oficiais próprios da instalação |
| Site e blog | [Publicação e identidade](docs/BLOG.md) | Hospedagem com SSH/Python 3 ou exportação manual |
| GA4, GTM, Search Console e Sheets | [Google e medição](docs/GOOGLE.md) | IDs próprios, consentimento e permissões por recurso |
| Leads e n8n | [Webhook e funil](docs/LEADS-N8N.md) | Endpoint privado e segredo exclusivo |
| E-mail | [Relatórios SMTP](docs/EMAIL.md) | SMTP e destinatário configurados |

Nenhuma senha de rede social é solicitada pelo aplicativo. Tokens/chaves de integração ficam criptografados no banco; o segredo mestre, a autorização Codex e a chave SSH ficam em configuração/volumes privados. Não são incluídos nas imagens ou no repositório.

## Limites e custos

- Hospedagem, domínio, serviços externos e limites de uso são responsabilidade do operador. Open source não significa créditos gratuitos em serviços de terceiros.
- Codex usa login oficial da conta que opera a instalação, sujeito a elegibilidade e limites. **Não transforma assinatura em API gratuita**, não compartilha contas e não troca silenciosamente para API paga.
- A equipe social usa Codex. A API OpenAI opcional atende artigos; não gera imagens nem substitui o executor social nesta versão.
- Reels são renderizados localmente a partir dos elementos da biblioteca. Vêm com faixa silenciosa, sem voz ou trilha musical. Não há geração automática de fotografia/vídeo por IA.
- Google pode atrasar dados; o painel consulta métricas a cada seis horas e a planilha a cada cinco minutos. Não promete atribuição causal ou cobertura de 100% das visitas.
- Qualificação e pagamento são informados por uma pessoa. Horários alternados são hipóteses editoriais, não prova de experimento causal aleatório.
- Esta é a primeira edição pública extraída de uma aplicação interna. Integrações foram exercitadas com testes e APIs simuladas; cada instalação precisa validar seus próprios acessos antes da publicação real.

## Desenvolvimento

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
node tests/test_tracking.js
node tests/test_calendar.js
python scripts/check_public_source.py
```

Veja [verificações da edição pública](docs/VALIDACAO.md), [arquitetura](docs/ARQUITETURA.md), [segurança](SECURITY.md), [contribuição](CONTRIBUTING.md) e [notas de terceiros](THIRD_PARTY.md). Código próprio sob [MIT](LICENSE); dependências preservam suas respectivas licenças.
