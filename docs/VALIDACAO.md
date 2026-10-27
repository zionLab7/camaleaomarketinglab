# Verificação da primeira edição pública

Data: 27/10/2026.

- 47 testes Python aprovados: autenticação/CSRF, fila e retomada, aprovação por hash, outbox, calendário, status e deduplicação de leads, APIs Google simuladas e personalização por segmento.
- Testes JavaScript aprovados: consentimento, sanitização, tentativas, confirmação e revogação.
- Scanner do código versionado aprovado: sem bancos, dados de cliente, credenciais ou dependências vendorizadas.
- Workflow Test and publish aprovado no GitHub; imagem GHCR acessível por download anônimo.
- Imagem construída e iniciada localmente com filesystem somente leitura, usuário sem root, capabilities removidas, volume novo e porta somente localhost. Health e login HTTP 200; banco vazio, auditoria válida e IDs de integração vazios.
- Navegador de teste: entrada, cadastro de empresa fictícia, preferências do copywriter, persistência após recarregar e biblioteca inicial. Sem erros JavaScript.
- Renderização real, sem chamada a modelo: post 1080×1350 e Reel 1080×1920, 30 fps, 20,011 s, H.264/AAC, conferência de composição aprovada. Faixa de áudio silenciosa.

Não foram reutilizadas contas de cliente para publicar posts de teste. Cada instalação deve conferir autorizações próprias, consentimento e primeiro envio real. Testes simulados não garantem acesso a todos os recursos da conta Meta/Google de um novo usuário.
