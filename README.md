# OpsFlow — Gestão e automação com Python e n8n

Projeto de portfólio de Leonardo Vieira para demonstrar suporte, desenvolvimento e automação. Aplicação independente com dados fictícios.

**Tecnologias:** Python · Flask · SQLite · HTML/CSS · n8n · HTTP/JSON · Microsoft Outlook OAuth.

**Fluxo principal:** abrir chamado Alta/Crítica → POST JSON → Webhook n8n → filtro de prioridade → alerta Outlook.

Desenvolvido com assistência de IA, com configuração da integração e testes manuais do fluxo realizados durante o projeto.

## O que o sistema faz

- Chamados de TI, Operacional e Financeiro, com prioridade, status e histórico no SQLite.
- Dashboard com contadores por status.
- Alerta por webhook ao criar chamados de prioridade Alta ou Crítica.
- Controle de cobranças e baixa de pagamentos.
- Atendimentos com check-in de localização mediante ação e consentimento do usuário.
- Registro de verificações de auditoria e rota `/health`.

## Instalar no Windows

Requer Python 3.10 ou superior. Abra o PowerShell na pasta que contém `app.py`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Abra http://127.0.0.1:5000 e mantenha o terminal aberto. Para encerrar, pressione Ctrl+C. O banco `opsflow.db` é criado na primeira inicialização. Não é necessário instalar n8n para explorar as telas.

## Configurar os alertas no n8n

1. Na sua instância n8n, importe `n8n/opsflow-alertas.json` pela opção de importar workflow de arquivo.
2. No nó **Enviar alerta Outlook**, substitua `seu-email@example.com` pelo destinatário desejado.
3. Conecte sua própria conta Microsoft Outlook pela credencial OAuth. Revise as permissões solicitadas.
4. No Webhook, confirme método POST e copie a **Production URL**. Se já houver outro fluxo com o mesmo caminho, escolha um caminho exclusivo.
5. Publique/ative o workflow.
6. Pare o Flask e execute no mesmo PowerShell, usando a URL copiada:

```powershell
$env:N8N_WEBHOOK_URL="COLE_A_PRODUCTION_URL_AQUI"
.\.venv\Scripts\python.exe app.py
```

A variável vale para esse terminal e seus processos filhos. Ao abrir outro PowerShell, configure-a novamente. Não há carregamento automático de `.env`. Nenhuma credencial Microsoft, URL pessoal ou destinatário real acompanha o pacote.

## Roteiro de demonstração (2 minutos)

1. Abra o dashboard e mostre os contadores.
2. Crie um chamado fictício com título, área TI, prioridade Crítica e descrição.
3. Mostre a confirmação de recebimento HTTP do n8n, a execução bem-sucedida e o e-mail recebido.
4. Crie um chamado de prioridade Baixa e confirme que ele fica salvo sem alerta.
5. Altere o status para Em andamento e depois Resolvido, clicando em Salvar e mostrando os contadores.
6. Mostre brevemente Financeiro, Operações e Auditoria.

**Abrir chamado** dispara a integração para Alta/Crítica. **Salvar**, na lista, só atualiza status e histórico; não envia e-mail.

## Contrato do webhook

O Flask envia JSON com `id`, `title`, `area`, `priority`, `description`, `status` e `created_at`. O Webhook do n8n disponibiliza esses campos em `$json.body`.

```json
{"id":1,"title":"Falha no sistema de cobrança","area":"TI","priority":"Crítica","description":"Exemplo fictício","status":"Aberto","created_at":"2026-10-19 23:00 UTC"}
```

## Validação e limites

Nos testes manuais, foi validado o envio Flask → n8n → Outlook com recebimento do e-mail; o usuário também confirmou que prioridade Baixa não envia alerta. O workflow deste pacote é uma versão reconstruída e sem credenciais: deve ser importado e testado na instância de destino.

O webhook responde imediatamente: HTTP 200 confirma recebimento, não entrega do e-mail. Consulte a execução no n8n. Há timeout de 3 segundos; falhas preservam o chamado e não têm reenvio automático. O banco original e os chamados de teste não foram incluídos.

Esta é uma demonstração local, sem autenticação, controle de acesso ou proteção CSRF. O servidor Flask de desenvolvimento não é destinado à produção. Antes de uso real, implemente esses controles, segredo de sessão, autenticação do webhook, fila de reenvio, monitoramento e implantação apropriada. Não exponha a aplicação nem cadastre dados reais de clientes nesta versão.

## Estrutura

- `app.py`: rotas, SQLite e envio HTTP.
- `templates/`: telas e tema compartilhado em `base.html`.
- `n8n/opsflow-alertas.json`: fluxo importável sem credenciais.
- `requirements.txt`: dependência da aplicação.
