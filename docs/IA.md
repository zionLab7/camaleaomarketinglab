# IA: Codex pela assinatura e API opcional

## Codex oficial

A aplicação chama `codex exec` no serviço editorial, com esquema JSON, ambiente reduzido e ferramentas desativadas. Sua assinatura precisa oferecer acesso ao Codex e ter limites disponíveis. Não se usa um endpoint privado do ChatGPT nem se converte a assinatura em uma chave API.

1. No Portainer, abra o console do serviço **editorial**, usuário `cml`, modo interativo.
2. Execute `codex login --device-auth`.
3. Abra o endereço oficial exibido, entre na sua conta e autorize o código dentro do prazo. Se o recurso precisar ser habilitado na segurança da conta, avalie e habilite você mesmo. Não envie o código para terceiros.
4. Execute `codex login status` e confirme autenticação ChatGPT.
5. Defina `CML_CODEX_ENABLED=true` na stack e recrie o editorial preservando `codex_auth`.
6. Os modelos são configuráveis em `CML_CREATIVE_MODEL`, `CML_CREATIVE_FALLBACK_MODEL` e `CML_BLOG_CODEX_MODEL`. Use modelos disponíveis à sua conta. A imagem fixa a versão do CLI; atualize/teste antes de trocar.

A rotina passa a preencher lacunas dos próximos seis dias, um conteúdo por dia em cada canal. A equipe social alterna carrosséis, posts e Reels ao longo da semana. Blog exige ao menos uma fonte editorial configurada. Esgotamento de limites gera erro/retentativa; não aciona cobrança por API automaticamente.

O volume contém autorização persistente da conta. Proteja console, backups e Portainer. Use uma conta autorizada por instalação; não distribua um auth.json em repositórios ou para usuários do projeto.

## API OpenAI opcional

Em **Conexões → OpenAI**, escolha API, informe modelo e chave privada. Há cobrança separada pela OpenAI. Essa configuração atende **artigos**; a equipe social continua exigindo o Codex. O aplicativo não faz geração automática de imagens pela API. O operador pode substituir/remover a chave pelo painel.

Não há LLM local. Renderizar HTML, vetores e vídeo com Chromium/FFmpeg é processamento local de mídia, não inferência de modelo.

Referência oficial consultada: [Autenticação Codex](https://learn.chatgpt.com/docs/auth). Recursos, planos, limites e disponibilidade podem mudar; confira sua conta antes de prometer operação contínua.
