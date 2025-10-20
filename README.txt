
# README - Projeto "WN Ponto Certo"

Este documento serve como um guia rápido para futuras manutenções e atualizações do sistema `WN Ponto Certo`.

## Visão Geral do Projeto

  * **Linguagem:** Python
  * **Interface:** Tkinter
  * **Compilador:** PyInstaller
  * **Bibliotecas Externas:**
      * `Pillow` (para imagens)
      * `reportlab` (para relatórios PDF)
      * `tkcalendar` (para os widgets de calendário)
  * **Arquivos Externos (Incluídos no `.exe`):**
      * `wn_logo.png` (usado nos relatórios)

-----

## Como Fazer uma Manutenção (Atualizar o Programa)

Siga este passo a passo **toda vez** que precisar corrigir um bug ou adicionar uma nova funcionalidade.

**Lembrete:** O arquivo `.exe` é um pacote fechado. Você não pode simplesmente trocar o script; você precisa **gerar um novo `.exe`** com o script atualizado.

### Passo 1: Edição do Código

1.  Faça todas as alterações desejadas diretamente no arquivo `wn_ponto_certo.py`.
2.  Salve o arquivo.

### Passo 2: Ativação do Ambiente

1.  Abra um terminal (CMD ou PowerShell) na pasta raiz do projeto (ex: `C:\..._ponto\`).
2.  Ative o ambiente virtual (venv). Se você não o ativou, o PyInstaller não encontrará as bibliotecas.
    ```bash: .\venv\Scripts\activate
    O Comando de Compilação (Obrigatório): pyinstaller --onefile --windowed --add-data "wn_logo.png;." --name "WN Ponto Certo" wn_ponto_certo.py
    ```
3.  Seu terminal deve agora mostrar `(venv)` no início da linha.

### Passo 3: Geração do Novo `.exe`

1.  Com o ambiente ativado e na pasta correta, execute o comando de compilação abaixo.
2.  Este comando irá excluir os arquivos antigos (`build/`, `dist/`) e criar novos.

**O Comando de Compilação (Obrigatório):**

```bash
pyinstaller --onefile --windowed --add-data "wn_logo.png;." --name "WN Ponto Certo" wn_ponto_certo.py
```

### Passo 4: Entrega ao Cliente

1.  Após o comando terminar, uma nova pasta `dist` será criada.
2.  Dentro da pasta `dist`, você encontrará o arquivo `WN Ponto Certo.exe` atualizado.
3.  Envie **apenas este arquivo `.exe`** para o seu cliente.

-----

## Observações Importantes

  * **O Banco de Dados:** O banco de dados (`ponto.db`) **NÃO** é incluído no `.exe`. Ele é criado (ou lido) na mesma pasta onde o cliente executa o programa.
  * **Atualização Segura:** Quando o cliente substituir o `.exe` antigo pelo novo, o banco de dados `ponto.db` dele **permanecerá intacto**. Ele não perderá nenhum dado.
  * **Arquivos do Projeto:** Mantenha sempre o `wn_ponto_certo.py` e o `wn_logo.png` juntos na pasta raiz do projeto. Não os mova para dentro da pasta `venv`.

-----

## Setup em um Novo Computador

Se você mover o projeto para um novo computador, precisará configurar o ambiente uma vez:

1.  Instale o Python (versão 3.10 ou superior).
2.  Abra o terminal na pasta do projeto.
3.  Crie o ambiente virtual:
    ```bash
    python -m venv venv
    ```
4.  Ative o ambiente:
    ```bash
    .\venv\Scripts\activate
    ```
5.  Instale todas as dependências:
    ```bash
    pip install pyinstaller Pillow reportlab tkcalendar
    ```
6.  Agora você está pronto para seguir o fluxo de manutenção normal.