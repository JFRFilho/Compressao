# CartZip — Compressão de arquivos

Aplicação web em Python para comprimir PDFs, imagens e outros arquivos. A interface permite enviar um arquivo, acompanhar o processamento e baixar o resultado, com uma meta de saída de **1 MB**.

Também permite unir um ou vários PDFs, na ordem selecionada, sem aplicar compressão e sem meta de tamanho para o PDF unido.

Se o resultado ultrapassar essa meta, a página informa o tamanho final e oferece o botão **“Baixar mesmo assim”**.

## Tecnologias

- **Python 3.11 e Flask:** servidor e rotas da aplicação.
- **Ghostscript:** recompressão e rasterização de PDFs.
- **pypdf:** união de PDFs sem passar pela rotina de compressão.
- **Pillow:** processamento de imagens e montagem de PDFs rasterizados.
- **ZIP Deflate:** compactação de outros formatos.
- **HTML, CSS e JavaScript:** interface, envio e apresentação do resultado.
- **Gunicorn:** execução do servidor dentro do contêiner.
- **Docker Compose:** construção, execução e armazenamento dos arquivos gerados.

## Como executar com Docker

Instale e inicie o Docker Desktop, com suporte a contêineres Linux e Docker Compose. No Windows, utilize o backend WSL 2.

Clone o repositório e entre na pasta:

```bash
git clone https://github.com/JFRFilho/Compressao.git
cd Compressao
```

Construa a imagem e inicie a aplicação:

```bash
docker compose up -d --build
```

Acesse **http://localhost:5000/**.

A primeira construção baixa a imagem Python e instala Ghostscript e as dependências. As próximas construções aproveitam o cache do Docker.

### Comandos úteis

```bash
# Aplicar alterações no código, no HTML ou no CSS
docker compose up -d --build

# Consultar os contêineres
docker compose ps

# Acompanhar os logs
docker compose logs -f --tail=100

# Parar a aplicação
docker compose down
```

Após alterar a interface, atualize o navegador com **Ctrl + F5** caso os estilos antigos permaneçam em cache.

## Como usar

1. Escolha um arquivo ou arraste-o para a área de envio.
2. Clique em **“Comprimir Arquivo”** e aguarde o processamento.
3. Confira o tamanho original, o tamanho final e a redução obtida.
4. Baixe o resultado. Quando a meta de 1 MB não for atingida, o aviso explica isso e o botão **“Baixar mesmo assim”** mostra o tamanho final.

Para unir PDFs, use a seção **Unir PDFs**, selecione um ou vários arquivos e clique em **Unir PDFs**. A lista mostra a ordem usada no documento final. Com um único PDF, o arquivo é copiado sem alterações.

## Como a compressão funciona

### PDFs

A aplicação tenta recomprimir o PDF com Ghostscript, na sequência de perfis `printer`, `ebook` e `screen`, interrompendo as tentativas quando atinge a meta.

Se essas tentativas não forem suficientes, ela rasteriza as páginas em imagens em tons de cinza, reduzindo progressivamente resolução e qualidade, e monta um novo PDF. Essa etapa pode reduzir a legibilidade e perder características do documento original, como texto selecionável, links e formulários.

### Imagens

Os formatos reconhecidos são JPG, JPEG, PNG, BMP, TIFF, WEBP e GIF. A aplicação gera uma imagem JPEG, reduzindo primeiro a qualidade e depois as dimensões, se necessário. Transparências recebem fundo branco; animações não são preservadas.

### Outros arquivos

A aplicação cria um ZIP com Deflate no nível máximo de compressão. A redução depende do conteúdo: formatos já comprimidos podem diminuir pouco ou até gerar um arquivo ligeiramente maior.

## Limites e comportamento

- **Limite da requisição de envio:** 500 MB, incluindo os dados do formulário.
- **Meta de saída:** 1 MB, calculado no código como 1.024 KB ou 1.048.576 bytes.
- A meta é uma tentativa, e não uma garantia para todo arquivo.
- Arquivos grandes, especialmente PDFs com muitas páginas, podem consumir bastante CPU e memória e levar vários minutos.
- A interface exibe um indicador de processamento; não há progresso por página nem estimativa de tempo.
- Resultados acima da meta continuam disponíveis para download e aparecem com um aviso explícito.
- Os tamanhos são exibidos em KB ou MB, conforme o tamanho do resultado.

## Armazenamento

O Compose utiliza o volume nomeado `uploads`, montado em `/app/uploads` dentro do contêiner. Assim, o armazenamento não depende de um caminho específico do Windows.

Os arquivos de entrada são removidos ao final do processamento. Os resultados ficam no volume e não possuem limpeza automática. O comando `docker compose down` preserva esses resultados.

> `docker compose down -v` também apaga o volume e os arquivos armazenados nele. Utilize apenas se quiser descartar esses dados.

## Estrutura do projeto

```text
Compressao/
├── app.py                 # Rotas e lógica de compressão
├── templates/
│   └── index.html         # Interface e interação com o servidor
├── static/
│   └── style.css          # Estilos e layout responsivo
├── Dockerfile             # Imagem Python, Ghostscript e Gunicorn
├── compose.yaml           # Serviço, porta e volume de uploads
├── requirements.txt       # Dependências Python
├── .dockerignore          # Arquivos excluídos da imagem
├── .gitignore             # Arquivos locais ignorados pelo Git
└── README.md
```

## Rotas

| Método | Rota | Função |
|---|---|---|
| GET | `/` | Exibe a interface. |
| POST | `/compress` | Recebe o campo `file` em `multipart/form-data`, processa e retorna JSON com os tamanhos, o nome da saída e `within_limit`. |
| POST | `/merge` | Recebe um ou mais campos `files` em `multipart/form-data` e retorna o nome e tamanho do PDF unido. |
| GET | `/download/<filename>` | Entrega o arquivo gerado para download. |

## Configurações principais

Em `app.py`, `MAX_KB` define a meta de saída e `MAX_CONTENT_LENGTH` define o limite da requisição. Os textos e a barra de tamanho da interface também precisam ser atualizados caso a meta seja alterada.

Em `compose.yaml`, o mapeamento `5000:5000` define a porta de acesso. No `Dockerfile`, o Gunicorn está configurado com dois workers, quatro threads por worker e timeout de 180 segundos. Esse timeout não representa um limite total garantido para cada compressão.

## Antes de publicar

O projeto foi preparado para execução local. Não possui autenticação, fila de processamento nem isolamento de arquivos por usuário. Envios simultâneos com o mesmo nome podem conflitar. Para disponibilizá-lo publicamente, essas partes precisam ser adaptadas.

As pastas `.venv`, `__pycache__` e `uploads` são locais e não devem ser enviadas ao GitHub. Caso já estejam versionadas, adicioná-las ao `.gitignore` não remove os arquivos do histórico nem do controle do Git.
