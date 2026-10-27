# Leads e n8n

O sistema aceita novos leads de um backend confiável; n8n é opcional. Adicione uma saída ao seu fluxo sem remover seu atendimento atual. Não exponha credenciais de ingestão em código do navegador.

## Nó HTTP Request

- Método POST, URL `https://SEU_PAINEL/api/webhooks/leads`.
- Autenticação Header Auth: nome `X-CML-Ingest-Key`, valor igual a `CML_INGEST_SECRET` da stack.
- Body JSON. Exemplo fictício de estrutura (não contém contatos reais):

```json
{
  "external_id": "site:execution-123456",
  "lead_ref": "lead:uuid-persistente",
  "name": "Contato de teste autorizado",
  "phone": "11900000000",
  "unit": "Equipe Centro",
  "category": "Consultoria",
  "analytics_consent": "rejected"
}
```

`external_id` identifica o evento/retry; `lead_ref` deve ser o UUID estável criado no formulário e preservado em tentativas. Sem esse campo, o backend precisa gerar uma referência estável. Reenviar a mesma referência não cria outro lead; reenviar o mesmo external_id com payload diferente é rejeitado.

Com consentimento, acrescente `attribution_first`, `attribution_last`, `assisted_content` e `landing_path` devolvidos pelo adaptador. Sem consentimento, o contato operacional é registrado, mas sem atribuição analítica. Use campos `name`/`phone` normalizados a partir dos seus próprios `nome`/`whatsapp`, se necessário. Telefone exige 10 a 13 dígitos. Não inclua dados extras que não sejam necessários.

Pode usar `?dry_run=1` com a mesma autenticação: valida e reverte a transação sem criar contato. Para conferir uma integração real, faça um único teste identificado e autorizado pela operação, sem disparar mensagens para terceiros. Header Auth não é obrigatório se o backend produzir `X-CML-Signature: sha256=...`, HMAC-SHA256 do corpo bruto com o mesmo segredo.

Não exporte credenciais junto ao workflow. Configure retry limitado, timeout e tratamento de erro; falha na medição não deve eliminar seu atendimento principal. Em “não interromper fluxo”, monitore também erros do nó para não perder a visibilidade de falhas.

## Funil comercial

Planilha privada: edite somente F:K. Status: Novo → Em atendimento → Qualificado / Não qualificado → Convertido / Perdido.

- Qualificado: defina o critério interno da empresa e aplique consistentemente.
- Convertido: pagamento confirmado; `Pago em` obrigatório. Valor pode ficar vazio, sem inventar receita.
- Perdido: motivo obrigatório.
- Correções/reversões atualizam agregados sem duplicar venda, preservando trilha de mudanças.

A planilha acompanha só os novos contatos recebidos pelo OS. Não importa o histórico existente. A capacidade inicial é 999 contatos; expanda o intervalo em código/configuração antes de atingir esse volume. O código lê `Leads!A1:R1000` intencionalmente para limitar a superfície operacional.

O endpoint `/api/webhooks/lead-status` aceita status pelo mesmo segredo, caso você prefira integrar um CRM no futuro; o conector nativo desta versão lê a planilha. Cliques WhatsApp não comprovam conversa, qualificação ou pagamento.
