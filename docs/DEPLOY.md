# Docker, Portainer e Traefik

## Pré-requisitos

Servidor Linux com Docker Standalone e Portainer, domínio próprio, DNS A/AAAA apontando para o servidor, Traefik já configurado para HTTPS e uma rede Docker externa compartilhada. Recomenda-se começar com 4 vCPU e 4–8 GB de RAM para Chromium/FFmpeg; a carga de renderização depende do conteúdo. O sistema não instala nem modifica seu Traefik.

A imagem publicada pelo workflow padrão é Linux amd64. Servidores ARM64 podem construir pelo código conforme a alternativa abaixo; a imagem também foi construída/testada localmente em ARM64.

O workflow **Test and publish** testa o código e publica uma imagem no GHCR após cada push em `main`. Antes de instalar, confirme o workflow verde e a imagem disponível. Se o GHCR exigir login, torne o pacote público nas configurações do GitHub Packages ou configure acesso de leitura ao registro no Portainer. A visibilidade pública do repositório não garante automaticamente a visibilidade do pacote.

## Importação pelo Git

1. Portainer → ambiente Docker → **Stacks → Add stack → Repository**.
2. Nome exclusivo: `camaleao-marketing`.
3. Repository URL: `https://github.com/zionLab7/camaleaomarketinglab`.
4. Repository reference: `refs/heads/main`.
5. Compose path: `compose.portainer.yml`.
6. Cadastre as variáveis abaixo no Portainer. O arquivo usa `environment` explícito, sem depender de `.env` dentro do Git nem de bind mounts relativos.
7. Deploy; espere `web` saudável e `editorial`/`publisher` em execução.
8. Abra `https://SEU_DOMINIO`, entre como `admin` e configure Marca e agentes.

### Obrigatórias

| Variável | Valor |
| --- | --- |
| `CML_DOMAIN` | Apenas domínio do painel, sem `https://` ou caminho |
| `CML_APP_SECRET` | Segredo aleatório exclusivo, pelo menos 32 caracteres |
| `CML_ADMIN_PASSWORD` | Senha exclusiva, pelo menos 16 caracteres; usada no primeiro início |
| `CML_INGEST_SECRET` | Segredo aleatório exclusivo de pelo menos 32 caracteres, se conectar leads |
| `TRAEFIK_NETWORK` | Nome real da rede externa do Traefik |
| `TRAEFIK_ENTRYPOINT` | Nome real do entrypoint HTTPS, padrão `websecure` |
| `TRAEFIK_CERTRESOLVER` | Resolver ACME já existente, padrão `letsencrypt` |

Gere cada segredo separadamente: `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`. Nunca coloque esses valores no Git ou em uma issue pública. O compose de produção força cookie Secure. Não publique a porta 8080 no host; o Traefik encaminha pela rede privada.

As demais variáveis estão em `.env.example`; use somente as integrações desejadas. `CML_CODEX_ENABLED=false` e `CML_BLOG_PUBLISH_ENABLED=false` são os padrões seguros. Instagram só publica após ativação em Conexões e aprovação de cada peça.

### Mais de uma instalação

Use nomes de stack, domínios, volumes e roteadores/serviços Traefik diferentes. Os labels de exemplo usam `cml`; no segundo stack, troque esses nomes nos labels para `cml-segundaempresa`. Nunca conecte empresas diferentes ao mesmo volume. Não há multi-tenancy ou isolamento por usuário dentro da aplicação.

## Se não puder usar GHCR

Clone o repositório no servidor, gere `.env`, construa `docker build -t camaleaomarketinglab:local .` e adapte o `image` dos três serviços do compose de produção para essa imagem local. Importe esse compose no editor do Portainer. Desative re-pull para imagens apenas locais. Não exponha o socket Docker à aplicação.

## Atualização e rollback

- Faça backup antes de atualizar. No Portainer, atualize a stack pelo Git e habilite pull da nova imagem.
- Para maior controle, use tag de versão ou digest `image@sha256:...` nos três serviços em seu próprio fork. `main` acompanha mudanças e não é imutável.
- Não remova volumes ao recriar containers. Migrações adicionam tabelas/colunas ao SQLite; não suponha que toda versão antiga aceita um banco mais novo.
- Rollback: pare os três serviços, restaure o banco e os volumes do mesmo backup, use o digest anterior e suba os serviços. Restaurar banco antigo descarta alterações posteriores: preserve uma cópia antes.

## Backup

Dados ficam em `marketing_data`; autorização Codex em `codex_auth`; chave SSH e known_hosts em `blog_ssh` (nomes reais recebem prefixo da stack).

Para backup consistente, pare editorial/publisher, execute pelo console do web:

```bash
python -c "import sqlite3; a=sqlite3.connect('/data/cml-marketing.db'); b=sqlite3.connect('/data/backup.db'); a.backup(b); b.close(); a.close()"
```

Copie `/data/backup.db`, `/data/brand.json`, `/data/library`, `/data/media`, snapshots e o restante necessário do volume para armazenamento privado. Guarde `CML_APP_SECRET` em um gerenciador de segredos: sem ele as credenciais e contatos criptografados não são recuperáveis. Faça backup privado também dos volumes de autenticação e SSH. Reinicie os executores. Nunca publique backups como artefatos do GitHub.

A senha inicial é armazenada como hash. Alterar `CML_ADMIN_PASSWORD` depois do primeiro início não troca o usuário já criado; use o procedimento de [primeiro acesso](PRIMEIRO-ACESSO.md) para redefinição.

Referências: [Portainer: stack pelo Git](https://docs.portainer.io/user/docker/stacks/add), [Docker: build](https://docs.docker.com/reference/compose-file/build/).
