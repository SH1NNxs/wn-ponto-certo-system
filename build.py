import os
import re
import subprocess
import sys

# --- Configurações ---
SCRIPT_PRINCIPAL = "wn_ponto_certo.py"
NOME_DO_EXE = "WN Ponto Certo"
ICONE = "wn_logo.ico"
RECURSOS = [
    ("wn_logo.png", "."),
    ("wn_logo.ico", ".")
]
# ---------------------

def encontrar_versao_atual():
    """Lê o SCRIPT_PRINCIPAL para encontrar a CURRENT_VERSION."""
    try:
        with open(SCRIPT_PRINCIPAL, "r", encoding="utf-8") as f:
            conteudo = f.read()
        
        # Procura a linha: CURRENT_VERSION = "vX.X.X"
        match = re.search(r'^CURRENT_VERSION\s*=\s*"v(\d+)\.(\d+)\.(\d+)"', conteudo, re.M)
        
        if not match:
            print(f"ERRO: Não consegui encontrar a linha 'CURRENT_VERSION = \"vX.X.X\"' em {SCRIPT_PRINCIPAL}")
            return None, None
            
        versao_encontrada = f"v{match.group(1)}.{match.group(2)}.{match.group(3)}"
        print(f"Versão atual encontrada: {versao_encontrada}")
        return versao_encontrada, (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    except FileNotFoundError:
        print(f"ERRO: Ficheiro não encontrado: {SCRIPT_PRINCIPAL}")
        return None, None

def sugerir_proxima_versao(major, minor, patch):
    """Sugere as próximas versões baseadas na atual."""
    v_patch = f"v{major}.{minor}.{patch + 1}"  # Ex: v1.0.0 -> v1.0.1
    v_minor = f"v{major}.{minor + 1}.0"      # Ex: v1.0.0 -> v1.1.0
    v_major = f"v{major + 1}.0.0"          # Ex: v1.0.0 -> v2.0.0
    return v_patch, v_minor, v_major

def obter_nova_versao(atual, partes_versao):
    """Pergunta ao utilizador qual será a nova versão."""
    v_patch, v_minor, v_major = sugerir_proxima_versao(*partes_versao)
    
    print("\nQual será a nova versão?")
    print(f"  1) Patch (Correção)  -> {v_patch}")
    print(f"  2) Minor (Recurso)   -> {v_minor}")
    print(f"  3) Major (Mudança)   -> {v_major}")
    print(f"  4) Digitar manualmente")
    
    while True:
        escolha = input("Escolha (1-4): ").strip()
        if escolha == '1':
            return v_patch
        if escolha == '2':
            return v_minor
        if escolha == '3':
            return v_major
        if escolha == '4':
            nova_versao = input("Digite a nova versão (ex: v1.2.3): ").strip()
            if re.match(r'^v\d+\.\d+\.\d+$', nova_versao):
                return nova_versao
            else:
                print("Formato inválido. Use 'vX.X.X'.")
        else:
            print("Escolha inválida.")

def atualizar_script(versao_antiga, versao_nova):
    """Substitui a string da versão no ficheiro .py"""
    try:
        with open(SCRIPT_PRINCIPAL, "r", encoding="utf-8") as f:
            conteudo = f.read()
        
        linha_antiga = f'CURRENT_VERSION = "{versao_antiga}"'
        linha_nova = f'CURRENT_VERSION = "{versao_nova}"'
        
        if linha_antiga not in conteudo:
            print(f"ERRO: Não consegui encontrar o texto exato '{linha_antiga}' no script.")
            return False
            
        conteudo = conteudo.replace(linha_antiga, linha_nova)
        
        with open(SCRIPT_PRINCIPAL, "w", encoding="utf-8") as f:
            f.write(conteudo)
            
        print(f"Script {SCRIPT_PRINCIPAL} atualizado para a versão {versao_nova}.")
        return True
    except Exception as e:
        print(f"ERRO ao atualizar o script: {e}")
        return False

def compilar_exe():
    """Executa o comando PyInstaller."""
    print("\nIniciando compilação (isto pode demorar)...")
    
    # Constrói o comando PyInstaller
    comando = [
        "pyinstaller",
        "--onefile",
        "--windowed",
        "--collect-data", "certifi", # Para o botão "Verificar Atualizações"
        "--name", NOME_DO_EXE,
        "--icon", ICONE
    ]
    
    # Adiciona os recursos (imagens, etc.)
    for recurso, destino in RECURSOS:
        comando.append(f"--add-data={recurso}{os.pathsep}{destino}")
        
    comando.append(SCRIPT_PRINCIPAL)
    
    print(f"A executar: {' '.join(comando)}")
    
    try:
        # Mostra a saída do PyInstaller em tempo real
        process = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()

        process.wait() # Espera o processo terminar
        
        if process.returncode == 0:
            print("\n---------------------------------")
            print(f"SUCESSO: '{NOME_DO_EXE}.exe' criado na pasta 'dist'!")
            return True
        else:
            print(f"\nERRO: PyInstaller falhou com código {process.returncode}.")
            return False
            
    except FileNotFoundError:
        print("\nERRO: O 'pyinstaller' não foi encontrado. Certifique-se de que o instalou ('pip install pyinstaller') e que está no PATH do sistema.")
        return False
    except Exception as e:
        print(f"\nERRO durante a compilação: {e}")
        return False

def main():
    print("--- Assistente de Build WN Ponto Certo ---")
    
    # 1. Encontrar versão
    versao_atual, partes_versao = encontrar_versao_atual()
    if not versao_atual:
        input("Pressione Enter para sair...")
        return

    # 2. Obter nova versão
    nova_versao = obter_nova_versao(versao_atual, partes_versao)
    if nova_versao == versao_atual:
        print("A versão não foi alterada. A compilar com a versão atual.")
    
    # 3. Atualizar o ficheiro .py
    if not atualizar_script(versao_atual, nova_versao):
        input("Pressione Enter para sair...")
        return
        
    # 4. Compilar
    if compilar_exe():
        print("\nPróximos passos:")
        print(f"  1. Envie (commit/push) o seu código .py para o repositório PRIVADO.")
        print(f"  2. Vá ao seu repositório PÚBLICO e crie um novo 'Lançamento'.")
        print(f"  3. Use a tag: {nova_versao}")
        print(f"  4. Anexe o ficheiro: dist\\{NOME_DO_EXE}.exe")
    
    input("\nPressione Enter para sair...")

if __name__ == "__main__":
    main()