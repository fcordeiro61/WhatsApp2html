# WhatsApp HTML

Conversor em Python que transforma uma conversa exportada do WhatsApp em um
HTML navegável, semelhante à visualização do aplicativo.

O arquivo gerado funciona localmente no navegador e não envia a conversa para
nenhum serviço externo.

## Recursos

- mensagens recebidas e enviadas em lados diferentes;
- busca por texto ou participante;
- filtro inclusivo por data inicial e data final;
- ordenação crescente ou decrescente;
- seleção de qual participante representa o usuário;
- personalização das cores das mensagens;
- visualização de imagens, vídeos e áudios;
- links para documentos e outros anexos;
- layout adaptado para computador e celular.

## Requisitos

- Python 3.10 ou superior;
- nenhuma biblioteca externa.

## Como usar

Entre na pasta do projeto:

```bash
cd ~/dev/whatsapp_html
```

Execute informando o TXT exportado e o caminho completo do HTML de saída:

```bash
python3 whatsapp_html.py \
  "/caminho/Conversa do WhatsApp.txt" \
  -o "/caminho/conversa.html"
```

O parâmetro `-o` deve apontar para um **arquivo HTML**, e não apenas para uma
pasta. Exemplo correto:

```bash
python3 whatsapp_html.py \
  "/mnt/u/WhatsApp-Carlos/Conversa do WhatsApp com Carlos.txt" \
  -o "/mnt/u/WhatsApp-Carlos/conversa-carlos.html"
```

Se `-o` for omitido, o HTML será criado ao lado do TXT com o mesmo nome.

## Anexos

Por padrão, o programa procura os anexos diretamente na mesma pasta do TXT.
Também é possível indicar outra pasta:

```bash
python3 whatsapp_html.py conversa.txt \
  --media-dir "/caminho/dos/anexos" \
  -o conversa.html
```

Para que os anexos continuem visíveis, mantenha o HTML e os arquivos de mídia
na organização utilizada durante a geração.

## Outras opções

```bash
python3 whatsapp_html.py conversa.txt \
  --me "Fabio" \
  --title "Conversa com Carlos" \
  --date-order dmy \
  -o conversa.html
```

- `--me`: participante cujas mensagens ficam alinhadas à direita;
- `--title`: título exibido no HTML;
- `--date-order dmy`: interpreta datas como dia/mês/ano;
- `--date-order mdy`: interpreta datas como mês/dia/ano.

## Filtro por período

No HTML aberto no navegador:

1. escolha a data em **De**;
2. escolha a data em **Até**;
3. as mensagens serão filtradas imediatamente;
4. use **Limpar datas** para exibir toda a conversa novamente.

O período inclui integralmente as datas inicial e final e pode ser combinado
com a busca textual.

## Testes

```bash
python3 -m unittest discover -s tests -v
```

## Privacidade

Não adicione conversas, mídias ou dados pessoais ao repositório. O `.gitignore`
bloqueia formatos comuns de exportação e anexos, mas revise sempre os arquivos
antes de qualquer commit.

## Licença

MIT.
