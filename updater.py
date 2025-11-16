import sys
import os
import time
import subprocess
import shutil
from datetime import datetime

# Este script recebe 3 argumentos do programa principal:
# sys.argv[1] -> PID do processo principal (para esperar que feche)
# sys.argv[2] -> Caminho do .exe ATUAL (antigo)
# sys.argv[3] -> Caminho do .exe NOVO (que foi baixado)

def log(message):
    """Grava um log para depuração."""
    try:
        # Tenta gravar o log ao lado do .exe principal
        log_dir = os.path.dirname(sys.argv[2])
    except:
        log_dir = os.getcwd() # Fallback
    
    log_file = os.path.join(log_dir, "updater-log.txt")
    
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
    except:
        pass # Falha silenciosamente se não conseguir gravar o log

def main():
    try:
        pid_to_wait_for = int(sys.argv[1])
        current_exe_path = sys.argv[2]
        new_exe_path = sys.argv[3]
    except Exception as e:
        log(f"ERRO: Argumentos inválidos. {e}\nArgs recebidos: {' '.join(sys.argv)}")
        return

    log(f"Updater iniciado. A esperar que o PID {pid_to_wait_for} feche.")
    
    # --- 1. Esperar que a aplicação principal feche ---
    timeout = 10 # 10 segundos
    while is_pid_running(pid_to_wait_for) and timeout > 0:
        time.sleep(1)
        timeout -= 1
        
    if is_pid_running(pid_to_wait_for):
        log("ERRO: Aplicação principal não fechou. A abortar atualização.")
        return
        
    log("Aplicação principal fechada. A continuar a atualização.")
    time.sleep(1) # Segundo extra por segurança

    # --- 2. Substituir o .exe antigo pelo novo ---
    try:
        log(f"A apagar ficheiro antigo: {current_exe_path}")
        if os.path.exists(current_exe_path):
            os.remove(current_exe_path)
            log("Ficheiro antigo apagado.")
        else:
            log("Ficheiro antigo não encontrado, a continuar.")

        log(f"A mover ficheiro novo de {new_exe_path} para {current_exe_path}")
        shutil.move(new_exe_path, current_exe_path)
        log("Ficheiro substituído.")

    except PermissionError as e:
        log(f"ERRO: Permissão negada. Não foi possível substituir o ficheiro. {e}")
        return
    except Exception as e:
        log(f"ERRO: Não foi possível substituir o ficheiro. {e}")
        return

    # --- 3. Reiniciar a nova aplicação ---
    try:
        log(f"A reiniciar: {current_exe_path}")
        subprocess.Popen([current_exe_path])
        log("Comando de reinício enviado.")
    except Exception as e:
        log(f"ERRO: Não foi possível reiniciar. {e}")

    log("Atualização concluída. O Updater vai fechar.")

def is_pid_running(pid):
    """Verifica se um processo está em execução (Apenas Windows)."""
    if os.name != 'nt':
        return False # Esta lógica é para Windows
        
    try:
        # Usa tasklist para verificar o PID
        output = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {pid}"], 
            stderr=subprocess.STDOUT, 
            text=True, 
            # Flag 0x08000000 = CREATE_NO_WINDOW (esconde a janela do terminal)
            creationflags=0x08000000 
        )
        return str(pid) in output
    except (subprocess.CalledProcessError, FileNotFoundError):
        # CalledProcessError = tasklist executou mas não achou o PID (fechou)
        return False
    except Exception:
        return False # Qualquer outro erro, assumir que não está a executar

if __name__ == "__main__":
    main()