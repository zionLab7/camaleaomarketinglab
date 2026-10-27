# Google: medição, busca e planilha

Coleta no navegador e leitura das APIs são configurações diferentes. Os IDs públicos de medição não são credenciais de acesso aos relatórios.

## 1. Recursos da empresa

- Crie/use uma propriedade **GA4** e um fluxo Web para o domínio correto. Guarde ID numérico da propriedade e ID de medição `G-…`.
- Crie/use um contêiner **GTM Web**. Guarde `GTM-…`.
- Verifique seu domínio ou URL prefixo no **Search Console**. O valor configurado deve ser exatamente `sc-domain:seusite.com` ou a URL prefixo registrada, incluindo barra quando aplicável.
- Para leads, crie uma **nova planilha privada**, sem histórico misturado. Crie abas `Leads` e `Como usar`, com pelo menos 1000 linhas. Copie a linha de cabeçalho de [leads-header.csv](../examples/leads-header.csv) para `Leads!A1:R1`, sem alterar títulos/ordem. Mantenha `Como usar!B12` disponível para verificar escrita.

Status recomendados para validação de dados na coluna F: `Novo`, `Em atendimento`, `Qualificado`, `Não qualificado`, `Convertido`, `Perdido`. Colunas G/H são datas; I é valor numérico na moeda definida pela instalação. Não cole contatos antigos: a integração acompanha os novos leads recebidos pelo webhook.

## 2. Credencial privada

No Google Cloud, crie um projeto próprio e ative apenas as APIs necessárias: **Google Analytics Data API**, **Search Console API**, **Google Sheets API**. Não é necessário vincular faturamento para esta arquitetura; confirme as cotas e políticas da sua organização.

Crie uma conta de serviço exclusiva, sem papel amplo de Editor/Owner no projeto. Dê acesso diretamente aos recursos:

- GA4: Leitor na propriedade desejada.
- Search Console: usuário restrito na propriedade desejada.
- Planilha: Editor somente na nova planilha, compartilhando com o e-mail da conta de serviço. Não abra acesso público ao arquivo.

Gere uma chave JSON se sua organização permitir. Em **Marca e agentes**, salve os IDs dos recursos que deseja integrar. Em **Conexões → Google**, envie o JSON diretamente no painel HTTPS. Recursos sem ID são ignorados; a verificação testa os configurados. Se houver planilha, escreve/lê somente a instrução `Como usar!B12`, não uma linha de contato. A chave é criptografada no servidor e pode ser substituída pelo mesmo formulário.

Não envie JSON por chat, commit, issue ou pasta pública. Revogue chaves antigas após substituir. O escopo Sheets autoriza escrita nos arquivos acessíveis à conta: limite a conta ao arquivo indicado.

## 3. GTM e consentimento

No contêiner, configure **uma Google tag** com o ID `G-…`, parâmetro `send_page_view=false` e trigger Initialization — All Pages. Publique. Desative captura automática de dados fornecidos pelo usuário, Google Signals/personalização e detecção automática/medição otimizada de formulários, rolagem etc. Não adicione outro tag GA4 ou evento genérico que duplique os eventos enviados pelo adaptador.

O adaptador é o responsável pelo banner e pelos eventos, e só carrega GTM após aceitar medição. Não instale o snippet padrão do GTM por fora dele: isso anteciparia a coleta. Se o site já tem CMP/tags, revise a instalação existente em vez de sobrepor dois banners.

Em Marca, informe GTM/GA4 e ative medição. O publicador do blog inclui o script nas próximas páginas exportadas. Para a LP/site, copie `tracking/cml-track.js` para `/blog/cml-track.js` e inclua no `<head>` antes de qualquer outro tag de analytics:

```html
<script id="cml-tracking" defer src="/blog/cml-track.js"
 data-gtm="GTM-SEUID" data-ga4="G-SEUID"></script>
```

Troque pelos seus IDs. `python tracking_install.py` imprime o snippet da configuração privada local. Alterar o painel não modifica automaticamente um site externo já instalado; atualize os IDs/script lá também.

Eventos disponíveis: page_view, início/erro de formulário, generate_lead após confirmação, clique CTA/telefone/WhatsApp, rolagem e leitura visível. **O sucesso do formulário precisa ser conectado explicitamente pelo seu código**, não apenas detectado por clique:

```javascript
const metadata = window.CMLTracking?.payload(form) || {};
// Inclua metadata no JSON enviado ao SEU backend/n8n.
try {
  const response = await enviarFormulario({...dadosDoContato, ...metadata});
  if (!response.ok) throw new Error('Falha de envio');
  window.CMLTracking?.submitted(form);
} catch (error) {
  window.CMLTracking?.failed(form, 'network');
}
```

Para erro de validação use `failed(form, 'validation')`. Nunca coloque o segredo de ingestão no navegador; o backend/n8n é quem autentica o registro no OS. Adapte `enviarFormulario` e os nomes dos campos ao site real.

## 4. Conferência

- Sem aceitar: zero chamadas Google Analytics/Tag Manager e formulário continua funcionando.
- Aceitar: evento no GA4 Tempo real; URL/título sem nome, telefone, e-mail ou parâmetros privados.
- Revogar/recarregar: coleta interrompida. Preferências acessíveis pelo rodapé.
- Enviar um formulário de teste autorizado pela operação: uma entrada no OS e depois na planilha. Repita o mesmo evento para conferir deduplicação; não use contatos de terceiros para teste.
- Atualize F:K; confira status no painel. `Convertido` exige `Pago em`; `Perdido` exige motivo.
- Consulte tarefas/registro. Google é consultado a cada 6 horas, últimos 28 dias até ontem; Sheets a cada 5 minutos. GSC pode atrasar e omitir linhas. A primeira consulta pode não ter resultados.

Atualize sua política de privacidade e avalie os requisitos da sua operação. O projeto implementa controles técnicos, não certifica conformidade jurídica automática.

Referências: [GA Data API](https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart), [autorização GSC](https://developers.google.com/webmaster-tools/v1/how-tos/authorizing), [consentimento Google](https://developers.google.com/tag-platform/security/guides/consent).
