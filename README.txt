=====================================
README - Projeto "WN Ponto Certo"
=====================================

Este documento serve como um guia rápido para futuras manutenções e atualizações do sistema WN Ponto Certo.

------------------------
Visao Geral do Projeto
------------------------

- Linguagem: Python
- Interface: Tkinter
- Compilador: PyInstaller
- Bibliotecas Externas:
    - Pillow (para imagens)
    - reportlab (para relatórios PDF)
    - tkcalendar (para os widgets de calendário)
- Arquivos Externos (Incluídos no .exe):
    - wn_logo.png (usado nos relatórios PDF)
    - wn_logo.ico (usado no ícone da janela e do arquivo .exe)


    Para resolver o erro de módulos ausentes no seu novo ambiente e criar o arquivo requirements.txt com base na estrutura do WN Ponto Certo, siga os passos abaixo.

Analisei seus arquivos (wn_ponto_certo.py e build.py) e identifiquei todas as dependências necessárias, incluindo a reportlab, que é essencial para a geração de relatórios PDF que seu sistema faz.

1. Instale todas as dependências de uma vez
Com o seu terminal aberto na pasta do projeto e o (venv) ativo, copie e cole este comando:

PowerShell
pip install Pillow tkcalendar requests packaging reportlab pyinstaller
Pillow: Para processamento de imagens (logos).

tkcalendar: Para o seletor de datas na interface.

requests & packaging: Para o sistema de atualização automática via GitHub.

reportlab: Para gerar os PDFs de fechamento de ponto.

pyinstaller: Para você conseguir usar o seu script build.py e gerar o executável.

2. Crie o arquivo requirements.txt
Agora que tudo está instalado no ambiente virtual, gere o arquivo de requisitos para nunca mais ter esse problema:

---------------------------------------------
3. Como usar o requirements.txt no futuro
---------------------------------------------

Se você precisar formatar o SSD novamente ou levar o projeto para outra máquina, basta criar o venv, ativá-lo e rodar:

PowerShell
pip install -r requirements.txt

-------------------------------------------
Como Fazer uma Manutencao (Atualizar o Programa)
-------------------------------------------

Siga este passo a passo TODA VEZ que precisar corrigir um bug ou adicionar uma nova funcionalidade.

LEMBRETE: O arquivo .exe é um pacote fechado. Voce nao pode simplesmente trocar o script; voce precisa GERAR UM NOVO .exe com o script atualizado.

Passo 1: Edicao do Codigo
1. Faça todas as alteracoes desejadas diretamente no arquivo wn_ponto_certo.py.
2. Salve o arquivo.

Passo 2: Ativacao do Ambiente
1. Abra um terminal (CMD ou PowerShell) na pasta raiz do projeto (ex: C:\...\projeto_ponto\).
2. Ative o ambiente virtual (venv). Se voce nao o ativou, o PyInstaller nao encontrará as bibliotecas.

   .\venv\Scripts\activate

3. Seu terminal deve agora mostrar (venv) no início da linha.

Passo 3: Geracao do Novo .exe
1. Com o ambiente ativado e na pasta correta, execute o comando de compilacao abaixo.
2. Este comando irá excluir os arquivos antigos (build/, dist/) e criar novos.

*******************************************************************************
*** O COMANDO DE COMPILACAO (OFICIAL) ***

python build.py

*******************************************************************************

Passo 4: Entrega ao Cliente
1. Após o comando terminar, uma nova pasta "dist" será criada.
2. Dentro da pasta "dist", voce encontrará o arquivo WN Ponto Certo.exe atualizado.
3. Envie apenas este arquivo .exe para o seu cliente.

------------------------
Observacoes Importantes
------------------------

- O Banco de Dados (ponto.db): O código foi ajustado (com 'sys.executable') para que o banco de dados seja salvo na MESMA PASTA do .exe (a pasta 'dist'), e nao em uma pasta temporária.

- Atualizacao Segura: Quando o cliente substituir o .exe antigo pelo novo, o banco de dados ponto.db dele permanecerá intacto. Ele nao perderá nenhum dado.

- Arquivos do Projeto: Mantenha sempre os arquivos principais juntos na pasta raiz do projeto:
    - wn_ponto_certo.py
    - wn_logo.png
    - wn_logo.ico

------------------------
Setup em um Novo Computador
------------------------

Se voce mover o projeto para um novo computador, precisará configurar o ambiente uma vez:

1. Instale o Python (versao 3.10 ou superior).
2. Abra o terminal na pasta do projeto.
3. Crie o ambiente virtual:
   python -m venv venv
4. Ative o ambiente:
   .\venv\Scripts\activate
5. Instale todas as dependências:
   'pip install pyinstaller Pillow reportlab tkcalendar'
6. Agora voce esta pronto para seguir o fluxo de manutencao normal.