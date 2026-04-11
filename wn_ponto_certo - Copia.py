@ -17,8 +17,8 @@ from packaging import version
import subprocess
import tempfile

# Use a tag exata que você criou no GitHub (ex: v1.0.0)
CURRENT_VERSION = "v1.2.3"
# --- VERSÃO ATUAL ---
CURRENT_VERSION = "v1.2.5"

# Tenta importar bibliotecas necessárias
try:
@ -26,6 +26,7 @@ try:
except ImportError:
    messagebox.showerror("Biblioteca Faltando", "Pillow: pip install Pillow")
    exit()

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
@ -37,13 +38,6 @@ try:
except ImportError:
    messagebox.showerror("Biblioteca Faltando", "reportlab: pip install reportlab")
    exit()
    from PIL import Image as PILImage, ImageTk

    # --- ADICIONE ESTA LINHA ---
    # Esta é a versão ATUAL do seu .exe.
    # Você DEVE atualizar este número antes de compilar um NOVO .exe para uma nova release.
    CURRENT_VERSION = "v1.2.3" 
    # --- FIM ---

# -------------------------
# BANCO DE DADOS (SQLite)
@ -94,7 +88,7 @@ def try_parse_datetime(s, format_to_try="%Y-%m-%d %H:%M:%S"):
            try: return datetime.strptime(s, "%Y/%m/%d %H:%M")
            except: return None

# --- FUNÇÃO calculate_deduction ATUALIZADA (NOVAMENTE) ---
# --- FUNÇÃO calculate_deduction ---
def calculate_deduction(minutes_late, sector=None):
    minutes_late = max(0, minutes_late)

@ -123,13 +117,11 @@ def calculate_deduction(minutes_late, sector=None):
            # Atraso * 3
            return minutes_late * 3
        elif minutes_late <= 30:
            # --- NOVA LÓGICA ESPECÍFICA SOLICITADA ---
            # (Primeiros 15 min * 3) + (Minutos 16 a 30 * 2) -> Total 75 min para 30 min de atraso
            penalty_first_15 = 15 * 3 # 45 minutos
            penalty_next_minutes = (minutes_late - 15) * 2 # Ex: (30-15)*2 = 15*2 = 30 min
            return penalty_first_15 + penalty_next_minutes # Total = 45 + 30 = 75 min
        else: # minutes_late > 30
            # --- NOVA BASE PARA > 30 min ---
            # Base de 75 min (calculada acima para 30 min) + (Excedente * 1)
            penalty_first_30 = 75 # (15*3) + (15*2)
            penalty_exceeding = (minutes_late - 30) * 1
@ -146,7 +138,6 @@ def calculate_deduction(minutes_late, sector=None):
            penalty_first_30 = 75 # Base 75 min
            penalty_exceeding = (minutes_late - 30) * 1
            return penalty_first_30 + penalty_exceeding
# --- FIM DA FUNÇÃO calculate_deduction ATUALIZADA ---

def format_minutes_to_hms(minutes):
    if minutes is None: return "00:00:00"
@ -184,6 +175,45 @@ def parse_hhmm_to_minutes(time_str):
    except ValueError:
        return 0

def calculate_period_data(entrada, saida, data_ref, turno_idx, sector, ignore_delay_flag=False):
    """
    Calcula minutos brutos, líquidos e dedução.
    Corrige contagem de horas antecipadas (Caso Iggor) e permite ignorar atrasos.
    """
    if not entrada: return 0, 0, 0
        
    # Define horário oficial (07:30 Manhã / 13:00 Tarde)
    horario_inicio_str = '07:30' if turno_idx < 2 else '13:00'
    jornada_inicio = datetime.strptime(f"{data_ref} {horario_inicio_str}", "%Y-%m-%d %H:%M")

    # Calcula diferença (negativo = chegou cedo, positivo = atrasado)
    minutes_diff = (entrada - jornada_inicio).total_seconds() / 60
    
    deduction_minutes = 0
    
    # Lógica de Atraso
    if minutes_diff > 0:
        if not ignore_delay_flag:
            deduction_minutes = calculate_deduction(minutes_diff, sector)
        
        # Se atrasou, o início conta a partir da punição (ou da entrada se punição for menor)
        inicio_com_punicao = jornada_inicio + timedelta(minutes=deduction_minutes)
        inicio_contabilizavel = max(entrada, inicio_com_punicao)
    else:
        # CORREÇÃO: Se chegou CEDO ou na hora, conta a partir da entrada física.
        inicio_contabilizavel = entrada

    if not saida: return 0, 0, deduction_minutes

    duration_bruto = (saida - entrada).total_seconds() / 60
    duration_liquido = 0
    
    if saida > inicio_contabilizavel:
        duration_liquido = (saida - inicio_contabilizavel).total_seconds() / 60
    
    return duration_bruto, duration_liquido, deduction_minutes

# --- Classe DatabaseManager ---
# --- Classe DatabaseManager ---
class DatabaseManager:
    def __init__(self, db_path=None):
@ -192,8 +222,50 @@ class DatabaseManager:
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_database()
        self.check_migrations() 
        self.populate_fixed_holidays()

    def check_migrations(self):
        """Verifica e cria colunas novas necessárias."""
        c = self.conn.cursor()
        try:
            c.execute("SELECT ignorar_atraso FROM horas_trabalhadas LIMIT 1")
        except sqlite3.OperationalError:
            print("Atualizando Banco de Dados: Adicionando coluna 'ignorar_atraso'...")
            c.execute("ALTER TABLE horas_trabalhadas ADD COLUMN ignorar_atraso INTEGER DEFAULT 0")
            self.conn.commit()

    def toggle_ignore_delay(self, matricula, data_str):
        """Alterna o status de ignorar atraso e recalcula o dia."""
        c = self.conn.cursor()
        c.execute("SELECT ignorar_atraso, periodos FROM horas_trabalhadas WHERE matricula=? AND data=?", (matricula, data_str))
        row = c.fetchone()
        if not row: return False
        
        novo_status = 1 if row['ignorar_atraso'] == 0 else 0
        periodos = json.loads(row['periodos'])
        minutos_totais_novo = 0
        novos_periodos = []
        func_info = self.get_funcionario_info(matricula)
        setor = func_info.get('setor', 'N/D')
        
        for i, p in enumerate(periodos):
            if p.get('entrada') and p.get('saida'):
                 ent = datetime.strptime(p['entrada'], "%Y-%m-%d %H:%M:%S")
                 sai = datetime.strptime(p['saida'], "%Y-%m-%d %H:%M:%S")
                 # Recalcula usando a nova função
                 _, liquido, deducao = calculate_period_data(ent, sai, data_str, i*2, setor, ignore_delay_flag=(novo_status==1))
                 minutos_totais_novo += liquido
                 p['minutos_liquidos'] = format_minutes_to_hms(liquido)
                 p['deducao_minutos'] = format_minutes_to_hms(deducao)
            novos_periodos.append(p)
            
        with self.conn:
            self.conn.execute("UPDATE horas_trabalhadas SET ignorar_atraso=?, minutos_totais=?, periodos=? WHERE matricula=? AND data=?", 
                              (novo_status, format_minutes_to_hms(minutos_totais_novo), json.dumps(novos_periodos), matricula, data_str))
            self.log_edicao(matricula, data_str, f"Ignorar: {row['ignorar_atraso']}", f"Ignorar: {novo_status}", "Alteração Manual Atraso")
        return True

    def create_database(self):
        c = self.conn.cursor()
        c.execute("""
@ -210,13 +282,12 @@ class DatabaseManager:
                extras_disponiveis_inicial INTEGER DEFAULT 0
            )
        """)
        c.execute("CREATE TABLE IF NOT EXISTS horas_trabalhadas (id INTEGER PRIMARY KEY, matricula TEXT, data TEXT, minutos_totais TEXT, periodos TEXT, criado_em DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(matricula, data))")
        c.execute("CREATE TABLE IF NOT EXISTS horas_trabalhadas (id INTEGER PRIMARY KEY, matricula TEXT, data TEXT, minutos_totais TEXT, periodos TEXT, ignorar_atraso INTEGER DEFAULT 0, criado_em DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(matricula, data))")
        c.execute("CREATE TABLE IF NOT EXISTS log_edicoes (id INTEGER PRIMARY KEY, matricula TEXT, data_ponto TEXT, data_edicao DATETIME DEFAULT CURRENT_TIMESTAMP, periodos_antigos TEXT, periodos_novos TEXT, justificativa TEXT, usuario TEXT DEFAULT 'SYSTEM/MANUAL')")
        c.execute("CREATE TABLE IF NOT EXISTS feriados (id INTEGER PRIMARY KEY, data TEXT UNIQUE, descricao TEXT, tipo TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS feriados_recorrentes (id INTEGER PRIMARY KEY, dia INTEGER, mes INTEGER, descricao TEXT, tipo TEXT, UNIQUE(dia, mes))")
        c.execute("CREATE TABLE IF NOT EXISTS punicoes (id INTEGER PRIMARY KEY, matricula TEXT, data_punicao TEXT, minutos_descontados REAL DEFAULT 0, motivo TEXT, data_registro DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (matricula) REFERENCES funcionarios (matricula))")
        c.execute("CREATE TABLE IF NOT EXISTS abonos (id INTEGER PRIMARY KEY, matricula TEXT, data TEXT, motivo TEXT, minutos_abonados REAL DEFAULT 0, data_registro DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(matricula, data))")
        c.execute("CREATE TABLE IF NOT EXISTS abonos (id INTEGER PRIMARY KEY, matricula TEXT, data TEXT, motivo TEXT, minutos_abonados REAL DEFAULT 0, data_registro DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(matricula, data))")
        self.conn.commit()

    def populate_fixed_holidays(self):
@ -553,7 +624,6 @@ class DatabaseManager:
        result = c.fetchone()
        return result['minutos_abonados'] if result and result['minutos_abonados'] is not None else 0

    # --- NOVO MÉTODO: get_stats_for_period ---
    def get_stats_for_period(self, matricula, start_date, end_date):
        """Coleta estatísticas de faltas, atrasos e punições para um período."""
        c = self.conn.cursor()
@ -620,7 +690,6 @@ class DatabaseManager:
            current_date_iter += timedelta(days=1)
            
        return stats
    # --- FIM DO NOVO MÉTODO ---

    def is_holiday(self, date_str):
        try:
@ -645,9 +714,6 @@ class DatabaseManager:
            return False

    def get_expected_daily_minutes(self, date_str, is_fichado, matricula):
        # --- LINHA CORRIGIDA ---
        print(f"DEBUG: Dentro de get_expected_daily_minutes, recebido data_str = {date_str}")
        # --- FIM DA CORREÇÃO ---
        """Retorna a carga horária esperada (débito) para um dia."""
        try:
            date_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
@ -857,8 +923,6 @@ class DatabaseManager:
                    current_sim_iter += timedelta(days=1)
                    continue # Pula o resto do cálculo

                print(f"DEBUG: Antes de chamar get_expected_daily_minutes para {matricula} em {data_str}")

                expected_minutes = self.get_expected_daily_minutes(data_str, is_fichado, matricula)

                minutos_trabalhados_dia = work_map.get(data_str, {}).get('minutos', 0)
@ -996,8 +1060,30 @@ class DatabaseManager:
            saldo_bh_antes = info_antes.get('banco_horas', 0)
            saldo_extras_antes = info_antes.get('extras_disponiveis', 0)

            novo_saldo_bh = saldo_bh_antes - minutos_a_deduzir_bh
            novo_saldo_extras = saldo_extras_antes - unidades_a_deduzir_extras
            # --- NOVA LÓGICA DE DEDUÇÃO INTELIGENTE ---
            
            # 1. Converte o saldo atual TODO para minutos
            # (Ex: 1 Extra e 10min vira 250 minutos totais)
            total_minutos_antes = (saldo_extras_antes * MINUTOS_UNIDADE_EXTRA) + saldo_bh_antes
            
            # 2. Converte o que está sendo pago/deduzido para minutos
            # (Ex: Pagar 1 Extra vira 240 minutos)
            total_minutos_deducao = (unidades_a_deduzir_extras * MINUTOS_UNIDADE_EXTRA) + minutos_a_deduzir_bh
            
            # 3. Realiza o abate do montante total
            total_minutos_novos = total_minutos_antes - total_minutos_deducao
            
            # 4. Redistribui o resultado para Extras e BH
            if total_minutos_novos < 0:
                # Se o saldo ficou negativo (Ex: -27 min), zeramos as Extras e o BH fica negativo
                novo_saldo_extras = 0
                novo_saldo_bh = total_minutos_novos
            else:
                # Se o saldo é positivo, recalculamos quantas Extras cheias cabem
                novo_saldo_extras = int(total_minutos_novos // MINUTOS_UNIDADE_EXTRA)
                novo_saldo_bh = total_minutos_novos % MINUTOS_UNIDADE_EXTRA
            
            # -----------------------------------------------------------

            with self.conn: # Garante que o UPDATE e o LOG estejam na mesma transação
                self.conn.execute("UPDATE funcionarios SET banco_horas = ?, extras_disponiveis = ? WHERE matricula = ?", (novo_saldo_bh, novo_saldo_extras, matricula))
@ -1037,97 +1123,151 @@ class DatabaseManager:
    def recalculate_full_balance_for_employee(self, matricula):
        c = self.conn.cursor()
        func_info = self.get_funcionario_info(matricula)
        # Se funcionário não for encontrado, não faz nada
        if not func_info:
             print(f"AVISO: Funcionário com matrícula {matricula} não encontrado para recálculo.")
             return
        if not func_info: return

        is_fichado = func_info.get('fichado', 0) == 1

        saldo_bh_minutos = func_info.get('banco_horas_inicial', 0)
        saldo_bh = func_info.get('banco_horas_inicial', 0)
        saldo_extras = func_info.get('extras_disponiveis_inicial', 0)

        c.execute("SELECT data, minutos_totais FROM horas_trabalhadas WHERE matricula = ? AND data >= ? ORDER BY data ASC", (matricula, SYSTEM_START_DATE))
        all_work_days = c.fetchall()

        work_map = {}
        for day in all_work_days:
            minutos_trabalhados = parse_hhmm_to_minutes(day['minutos_totais'])
            work_map[day['data']] = minutos_trabalhados
        # 1. Soma saldo gerado pelo trabalho dia a dia
        c.execute("SELECT data, minutos_totais FROM horas_trabalhadas WHERE matricula=? AND data >= ? ORDER BY data", (matricula, SYSTEM_START_DATE))
        work_map = {r['data']: parse_hhmm_to_minutes(r['minutos_totais']) for r in c.fetchall()}

        try:
            start_dt = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
            # --- MODIFICAÇÃO (Não calcular dia de hoje) ---
            # O recálculo oficial só vai até ONTEM.
            end_dt = SYSTEM_CURRENT_DATE - timedelta(days=1)
            # --- FIM DA MODIFICAÇÃO ---
        except ValueError:
            print(f"Erro ao parsear datas de início/fim em recalculate para {matricula}")
            return
        except: return

        if start_dt > end_dt:
             self.conn.execute("UPDATE funcionarios SET banco_horas = ?, extras_disponiveis = ? WHERE matricula = ?", (saldo_bh_minutos, saldo_extras, matricula))
             self.conn.commit()
             return
        if start_dt <= end_dt:
            curr = start_dt
            while curr <= end_dt:
                d_str = curr.isoformat()
                trabalhado = work_map.get(d_str, 0)

        current_date_iter = start_dt
        while current_date_iter <= end_dt:
            data_str = current_date_iter.isoformat()

            expected_minutes = self.get_expected_daily_minutes(data_str, is_fichado, matricula) # Chama a função corrigida

            minutos_trabalhados_dia = work_map.get(data_str, 0)
            excedente_dia = minutos_trabalhados_dia - expected_minutes
            saldo_bh_minutos += excedente_dia

            while saldo_bh_minutos >= MINUTOS_UNIDADE_EXTRA:
                saldo_bh_minutos -= MINUTOS_UNIDADE_EXTRA
                saldo_extras += 1
            while saldo_bh_minutos < 0 and saldo_extras > 0:
                saldo_bh_minutos += MINUTOS_UNIDADE_EXTRA
                saldo_extras -= 1
                # --- Lógica Não Fichado ---
                if not is_fichado and trabalhado == 0:
                    esperado = 0 
                else:
                    # get_expected_daily_minutes JÁ subtrai o abono da expectativa.
                    esperado = self.get_expected_daily_minutes(d_str, is_fichado, matricula)

            current_date_iter += timedelta(days=1)
                # Saldo do dia
                saldo_bh += (trabalhado - esperado)

        c.execute("SELECT SUM(minutos_descontados) as total_punicao FROM punicoes WHERE matricula = ? AND data_punicao >= ?", (matricula, SYSTEM_START_DATE))
        punicao_total = c.fetchone()['total_punicao'] or 0
        saldo_bh_minutos -= punicao_total
        while saldo_bh_minutos < 0 and saldo_extras > 0:
             saldo_bh_minutos += MINUTOS_UNIDADE_EXTRA
             saldo_extras -= 1
                # Normalização diária (converte excesso de BH para Extras)
                while saldo_bh >= MINUTOS_UNIDADE_EXTRA:
                    saldo_bh -= MINUTOS_UNIDADE_EXTRA
                    saldo_extras += 1
                while saldo_bh < 0 and saldo_extras > 0:
                    saldo_bh += MINUTOS_UNIDADE_EXTRA
                    saldo_extras -= 1

                curr += timedelta(days=1)

        c.execute("SELECT periodos_antigos, periodos_novos FROM log_edicoes WHERE matricula = ? AND justificativa = 'Pagamento/Dedução Saldo' AND data_ponto >= ?", (matricula, SYSTEM_START_DATE))
        logs_pagamento = c.fetchall()
        # 2. Subtrai Punições
        c.execute("SELECT SUM(minutos_descontados) as t FROM punicoes WHERE matricula=? AND data_punicao >= ?", (matricula, SYSTEM_START_DATE))
        total_punicoes = c.fetchone()['t']
        saldo_bh -= (total_punicoes or 0)

        total_extras_pagos = 0
        total_bh_pagos = 0 # (Não implementado, mas para futuro)
        # Normaliza após punições
        while saldo_bh < 0 and saldo_extras > 0: saldo_bh += MINUTOS_UNIDADE_EXTRA; saldo_extras -= 1

        for log in logs_pagamento:
        # 3. Subtrai Pagamentos (AQUI ESTAVA O ERRO: Agora lê BH e Extras)
        c.execute("SELECT periodos_antigos, periodos_novos FROM log_edicoes WHERE matricula=? AND justificativa='Pagamento/Dedução Saldo'", (matricula,))
        for log in c.fetchall():
            try:
                antigo_str = log['periodos_antigos']
                novo_str = log['periodos_novos']
                # Lê Extras
                ant_extra = re.search(r'Extras: (\-?\d+)', log['periodos_antigos'])
                nov_extra = re.search(r'Extras: (\-?\d+)', log['periodos_novos'])
                if ant_extra and nov_extra: 
                    diff_extras = int(ant_extra.group(1)) - int(nov_extra.group(1))
                    saldo_extras -= diff_extras

                # Lê Banco de Horas (NOVO)
                ant_bh = re.search(r'BH: ([\-\d:]+)', log['periodos_antigos'])
                nov_bh = re.search(r'BH: ([\-\d:]+)', log['periodos_novos'])
                if ant_bh and nov_bh:
                    # Converte HH:MM para minutos
                    min_ant = parse_hhmm_to_minutes(ant_bh.group(1))
                    min_nov = parse_hhmm_to_minutes(nov_bh.group(1))
                    diff_bh = min_ant - min_nov
                    saldo_bh -= diff_bh
                    
            except Exception as e: 
                print(f"Erro parse log recálculo: {e}")
                pass

        # 4. Normalização Final (Garante consistência)
        # Se sobrar muito BH positivo, vira extra
        while saldo_bh >= MINUTOS_UNIDADE_EXTRA:
            saldo_bh -= MINUTOS_UNIDADE_EXTRA
            saldo_extras += 1
        
        # Se BH negativo e tem extra, queima extra para cobrir
        while saldo_bh < 0 and saldo_extras > 0:
            saldo_bh += MINUTOS_UNIDADE_EXTRA
            saldo_extras -= 1

                # Extrai "Extras: X"
                extras_antigo_match = re.search(r'Extras: (\-?\d+)', antigo_str)
                extras_novo_match = re.search(r'Extras: (\-?\d+)', novo_str)
        # Se Saldo de Extras ficar negativo, converte dívida de extra em dívida de BH (opcional, mas mantém lógica limpa)
        while saldo_extras < 0: 
            saldo_extras += 1
            saldo_bh -= MINUTOS_UNIDADE_EXTRA

                if extras_antigo_match and extras_novo_match:
                    extras_antigo = int(extras_antigo_match.group(1))
                    extras_novo = int(extras_novo_match.group(1))
                    total_extras_pagos += (extras_antigo - extras_novo)
        self.conn.execute("UPDATE funcionarios SET banco_horas=?, extras_disponiveis=? WHERE matricula=?", (saldo_bh, saldo_extras, matricula))
        self.conn.commit()

            except Exception as e:
                print(f"Erro ao parsear log de pagamento para recálculo: {e}")
    
    def reprocess_daily_data(self, matricula):
        """
        Força o reprocessamento de cada dia importado usando a lógica de cálculo ATUAL.
        Isso corrige dias importados antes de atualizações de regras (ex: chegada antecipada).
        """
        c = self.conn.cursor()
        # Pega todos os dias desse funcionário
        c.execute("SELECT data, periodos, ignorar_atraso FROM horas_trabalhadas WHERE matricula=?", (matricula,))
        rows = c.fetchall()
        
        func_info = self.get_funcionario_info(matricula)
        setor = func_info.get('setor', 'N/D')

        saldo_extras -= total_extras_pagos
        with self.conn:
            for row in rows:
                data_str = row['data']
                ignorar_atraso = row['ignorar_atraso'] == 1
                try:
                    periodos_json = json.loads(row['periodos'])
                except: continue
                
                if not periodos_json: continue

        while saldo_extras < 0:
             saldo_extras += 1
             saldo_bh_minutos -= MINUTOS_UNIDADE_EXTRA
                minutos_totais_novo = 0
                novos_periodos = []
                
                for i, p in enumerate(periodos_json):
                    entrada_str = p.get('entrada')
                    saida_str = p.get('saida')
                    
                    if not entrada_str: 
                        novos_periodos.append(p)
                        continue

        self.conn.execute("UPDATE funcionarios SET banco_horas = ?, extras_disponiveis = ? WHERE matricula = ?", (saldo_bh_minutos, saldo_extras, matricula))
        self.conn.commit()
                    ent = datetime.strptime(entrada_str, "%Y-%m-%d %H:%M:%S")
                    sai = datetime.strptime(saida_str, "%Y-%m-%d %H:%M:%S") if saida_str else None
                    
                    # RECALCULA usando a função global atualizada (que aceita chegada cedo)
                    # i*2 garante que o turno da tarde (index 1) vire turno_idx 2 (13:00)
                    _, liquido, deducao = calculate_period_data(ent, sai, data_str, i*2, setor, ignore_delay_flag=ignorar_atraso)
                    
                    minutos_totais_novo += liquido
                    
                    # Atualiza os detalhes no JSON para o relatório ficar correto também
                    p['minutos_liquidos'] = format_minutes_to_hms(liquido)
                    p['deducao_minutos'] = format_minutes_to_hms(deducao)
                    novos_periodos.append(p)

                # Salva o novo total calculado no Banco
                self.conn.execute("UPDATE horas_trabalhadas SET minutos_totais=?, periodos=? WHERE matricula=? AND data=?", 
                                  (format_minutes_to_hms(minutos_totais_novo), json.dumps(novos_periodos), matricula, data_str))
    
    def get_detailed_stats_for_period(self, matricula, start_date, end_date):
        """Gera estatísticas detalhadas simulando o período."""
@ -1300,112 +1440,65 @@ def import_glog_txt(filepath, db_manager, logger=print):
    unique_employees = set()
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f.readlines()[1:]: # Pula cabeçalho
            for line in f.readlines()[1:]:
                parts = re.split(r'\s+', line.strip())
                if len(parts) < 8: continue
                try:
                    matricula = str(parts[2]).zfill(8)
                    nome = str(parts[3]).strip()
                    if len(parts) >= 8 and parts[6] and parts[7]:
                        dt_str = f"{parts[6]} {parts[7]}"
                        dt = try_parse_datetime(dt_str)
                        if dt:
                            # Filtra pela constante global
                            if dt.date() < datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date():
                                 continue # Ignora datas anteriores ao início
                            unique_employees.add((matricula, nome))
                            employees_points_raw[matricula][dt.date().isoformat()].append({"datetime": dt})
                        else:
                            logger(f"AVISO: Formato de data/hora inválido na linha: {line.strip()}")
                    else:
                        logger(f"AVISO: Dados de data/hora ausentes na linha: {line.strip()}")
                except IndexError:
                     logger(f"AVISO: Linha com formato inesperado (IndexError): {line.strip()}")
                except Exception as e:
                     logger(f"AVISO: Erro ao processar linha: {line.strip()} - Erro: {e}")
                     continue
                    dt_str = f"{parts[6]} {parts[7]}"
                    dt = try_parse_datetime(dt_str)
                    if dt and dt.date() >= datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date():
                        unique_employees.add((matricula, nome))
                        employees_points_raw[matricula][dt.date().isoformat()].append({"datetime": dt})
                except: continue
    except Exception as e:
        logger(f"ERRO LEITURA ARQUIVO: {e}")
        return [], set()
        logger(f"ERRO LEITURA: {e}"); return [], set()

    logger(f"Funcionários detectados no arquivo: {len(unique_employees)}")
    existing_matriculas = db_manager.get_all_funcionarios_matriculas()
    new_employees_list = []
    processed_matriculas_in_file = set()
    for matricula, nome in unique_employees:
        processed_matriculas_in_file.add(matricula)
        if matricula not in existing_matriculas:
            new_employees_list.append((matricula, nome))
    new_employees_list = [(m, n) for m, n in unique_employees if m not in existing_matriculas]
    processed_matriculas = set(m for m, n in unique_employees)

    for matricula, dias in sorted(employees_points_raw.items()):
        func_info = db_manager.get_funcionario_info(matricula)
        sector = func_info.get('setor', 'N/D') if func_info else 'N/D'

        for data, pontos_brutos in sorted(dias.items()):
            # Checagem extra por segurança
            if data < SYSTEM_START_DATE:
                continue

            pontos_brutos.sort(key=lambda x: x["datetime"])
            periodos_trabalhados, minutos_trabalhados_decimal_total = [], 0
            horarios_sequenciais = [p["datetime"] for p in pontos_brutos]
            periodos_trabalhados = []
            minutos_trabalhados_total = 0
            horarios = [p["datetime"] for p in pontos_brutos]

            i = 0
            while i < len(horarios_sequenciais):
                entrada = horarios_sequenciais[i]
                saida = None
            while i < len(horarios):
                entrada = horarios[i]
                saida = horarios[i+1] if i + 1 < len(horarios) else None
                
                if i + 1 < len(horarios_sequenciais):
                    saida = horarios_sequenciais[i+1]
                else:
                    pass # Última batida ímpar
                # USA A NOVA FUNÇÃO (Correção Iggor)
                bruto, liquido, deducao = calculate_period_data(entrada, saida, data, i, sector)
                
                turno = "Manhã" if i < 2 else "Tarde"
                jornada_inicio = datetime.strptime(f"{data} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")
                minutes_late = max(0, (entrada - jornada_inicio).total_seconds() / 60)
                delay_deduction_minutes = calculate_deduction(minutes_late, sector)
                if saida and saida < entrada: i += 2; continue

                minutos_trabalhados_total += liquido
                
                if saida: # Par completo
                    if saida < entrada:
                       logger(f"AVISO: {matricula} {data}: Saída ({saida}) anterior à entrada ({entrada}). Ignorando período.")
                       i += 2
                       continue
                    inicio_efetivo = jornada_inicio + timedelta(minutes=delay_deduction_minutes)
                    inicio_real_contagem = max(entrada, inicio_efetivo)
                    duration_minutes_liquido = 0
                    if saida > inicio_real_contagem:
                        duration_minutes_liquido = (saida - inicio_real_contagem).total_seconds() / 60
                    duration_minutes_bruto = (saida - entrada).total_seconds() / 60
                    minutos_trabalhados_decimal_total += duration_minutes_liquido
                    periodos_trabalhados.append({
                        "entrada": str(entrada), "saida": str(saida),
                        "minutos_brutos": format_minutes_to_hms(duration_minutes_bruto),
                        "deducao_minutos": format_minutes_to_hms(delay_deduction_minutes),
                        "minutos_liquidos": format_minutes_to_hms(duration_minutes_liquido)
                    })
                    i += 2
                else: # Batida ímpar
                    logger(f"AVISO: {matricula} {data}: Batida ímpar detectada ({entrada}). Salva como incompleta.")
                    periodos_trabalhados.append({
                        "entrada": str(entrada), "saida": None,
                        "minutos_brutos": "00:00:00",
                        "deducao_minutos": format_minutes_to_hms(delay_deduction_minutes),
                        "minutos_liquidos": "00:00:00"
                    })
                    i += 1
                periodos_trabalhados.append({
                    "entrada": str(entrada),
                    "saida": str(saida) if saida else None,
                    "minutos_brutos": format_minutes_to_hms(bruto),
                    "deducao_minutos": format_minutes_to_hms(deducao),
                    "minutos_liquidos": format_minutes_to_hms(liquido)
                })
                i += 2 if saida else 1

            if periodos_trabalhados:
                # Mantém flag ignorar_atraso se existir
                db_manager.insert_horas_trabalhadas({
                    "matricula": matricula,
                    "data": data,
                    "minutos_totais": format_minutes_to_hms(minutos_trabalhados_decimal_total),
                    "matricula": matricula, "data": data,
                    "minutos_totais": format_minutes_to_hms(minutos_trabalhados_total),
                    "periodos": periodos_trabalhados
                })
            elif len(horarios_sequenciais) > 0:
                logger(f"AVISO: {matricula} {data}: Nenhuns períodos de trabalho válidos formados a partir das batidas.")

    return new_employees_list, processed_matriculas_in_file

    return new_employees_list, processed_matriculas

# --- Classe DateRangePicker ---
class DateRangePicker:
@ -1546,6 +1639,36 @@ class App:
            self.on_calendar_click()

        self.root.protocol("WM_DELETE_WINDOW", self.on_app_close)
    
    # Adicione dentro da class App
    def show_context_menu(self, event):
        item = self.tree_viewer.identify_row(event.y)
        if item:
            self.tree_viewer.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def toggle_ignore_delay_context(self):
        sel = self.tree_viewer.selection()
        if not sel: return
        
        # O iid é uma string composta (devido ao bind com DB), mas o values[0] tem a matricula
        vals = self.tree_viewer.item(sel[0], 'values')
        if not vals: return
        
        matricula = vals[0]
        data_ptbr = vals[2]
        
        try:
            data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d")
        except: return
        
        if self.db.toggle_ignore_delay(matricula, data_db):
            self.append_log(f"Atraso ignorado/ativado para {matricula} em {data_db}. Recalculando...")
            self.db.recalculate_full_balance_for_employee(matricula)
            self.load_point_viewer(force_reload=True)
            messagebox.showinfo("Sucesso", "Status de atraso alterado!")
        else:
            messagebox.showerror("Erro", "Não há registros importados neste dia para alterar.")

    def setup_styles(self):
        style = ttk.Style()
@ -1613,20 +1736,18 @@ class App:
        app_title = tk.Label(header_frame, text="WN Ponto Certo", font=("Segoe UI", 20, "bold"), fg="white", bg="#0a192f")
        app_title.pack(side=tk.LEFT)

# --- MODIFICAÇÃO: Frame de Ações dividido em duas linhas ---
        # --- Frame de Ações dividido em duas linhas ---
        actions_frame_container = tk.Frame(top_frame, bg="#0a192f")
        actions_frame_container.pack(fill=tk.X, pady=(10,0))

        # --- Botões da Direita (Sair, Atualizar) ---
        # Criamos um frame separado para os botões da direita
        right_buttons_frame = tk.Frame(actions_frame_container, bg="#0a192f")
        right_buttons_frame.pack(side=tk.RIGHT, anchor='n', padx=(10, 0)) # 'n' para alinhar ao topo
        right_buttons_frame.pack(side=tk.RIGHT, anchor='n', padx=(10, 0)) 
        
        ttk.Button(right_buttons_frame, text="🔄 Verificar Atualizações", command=self.check_for_updates).pack(side=tk.TOP, fill=tk.X, pady=(0,5))
        ttk.Button(right_buttons_frame, text="🚪 Sair", command=self.on_app_close, style='TButton').pack(side=tk.TOP, fill=tk.X)

        # --- Botões da Esquerda (Duas fileiras) ---
        # Este frame vai conter as duas fileiras de botões
        left_buttons_frame = tk.Frame(actions_frame_container, bg="#0a192f")
        left_buttons_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

@ -1642,17 +1763,19 @@ class App:
        
        # Fileira 2
        actions_frame_row2 = tk.Frame(left_buttons_frame, bg="#0a192f")
        actions_frame_row2.pack(fill=tk.X, pady=(5,0)) # Adiciona um espaçamento entre as fileiras
        actions_frame_row2.pack(fill=tk.X, pady=(5,0)) 

        ttk.Button(actions_frame_row2, text=" Punição", command=self.on_add_punishment, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row2, text="Saldos Iniciais", command=self.on_edit_initial_balance, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row2, text="Abonar Falta", command=self.on_abone_falta, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row2, text="Relatório Detalhado", command=self.on_detailed_report, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row2, text="📄 Exportar Log", command=self.on_export_log, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row2, text="⚖️ Punição", command=self.on_add_punishment, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row2, text="🔢 Saldos Iniciais", command=self.on_edit_initial_balance, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row2, text="✅ Abonar Falta", command=self.on_abone_falta, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        
        # --- FIM DA MODIFICAÇÃO ---
        # --- NOVO BOTÃO AQUI ---
        ttk.Button(actions_frame_row2, text="⏳ Abonar Atraso", command=self.toggle_ignore_delay_context, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        # -----------------------

        # (O resto do seu código original)
        ttk.Button(actions_frame_row2, text="📊 Relatório Detalhado", command=self.on_detailed_report, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row2, text="📄 Exportar Log", command=self.on_export_log, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        
        log_frame = ttk.LabelFrame(main_frame, text=" Log ", style='TLabelframe')
        log_frame.grid(row=1, column=1, sticky="nsew", pady=5, padx=(5, 0))
        self.log_area = scrolledtext.ScrolledText(log_frame, bg="#112240", fg="#a8b2d1", insertbackground="white", font=("Consolas", 9), relief=tk.FLAT, borderwidth=5)
@ -1660,6 +1783,39 @@ class App:

        self.setup_point_viewer(main_frame)

    def show_context_menu(self, event):
        item = self.tree_viewer.identify_row(event.y)
        if item:
            self.tree_viewer.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def toggle_ignore_delay_context(self):
        sel = self.tree_viewer.selection()
        if not sel: 
            messagebox.showwarning("Seleção Necessária", "Por favor, selecione um dia na tabela abaixo para abonar o atraso.")
            return
        
        vals = self.tree_viewer.item(sel[0], 'values')
        if not vals: return
        
        matricula = vals[0]
        data_ptbr = vals[2]
        
        try:
            data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d")
        except: return
        
        # Chama a função do banco que altera o status 'ignorar_atraso'
        if self.db.toggle_ignore_delay(matricula, data_db):
            self.append_log(f"Status de atraso alterado para {matricula} em {data_db}. Recalculando...")
            # Recalcula o saldo total
            self.db.recalculate_full_balance_for_employee(matricula)
            # Recarrega a tela para mostrar os novos valores (sem a multiplicação)
            self.load_point_viewer(force_reload=True)
            messagebox.showinfo("Sucesso", "Status de atraso alterado! A multiplicação foi removida/adicionada para este dia.")
        else:
            messagebox.showerror("Erro", "Não há registros importados neste dia para alterar.")
            
    def on_app_close(self):
        if self.unsaved_edits:
            answer = messagebox.askyesnocancel("Alterações Não Salvas",
@ -2851,19 +3007,15 @@ class App:
        cmb_func.pack(anchor="w", pady=(0, 20)); 
        tk.Label(form_frame, text="2. Período:", bg="#0a192f", fg="#ccd6f6", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5))

        # --- MODIFICAÇÃO: Substituindo os dois calendários ---
        # Removido 'period_frame', 'cal_start', 'cal_end'
        date_picker = DateRangePicker(form_frame, self.BG_COLOR, self.style_colors_dict)
        date_picker.pack(pady=10, padx=10)
        
        # Pré-seleciona as datas da tela principal
        if self.selected_start_date:
            date_picker.cal.selection_set(self.selected_start_date)
            date_picker._on_calendar_click()
        if self.selected_end_date:
            date_picker.cal.selection_set(self.selected_end_date)
            date_picker._on_calendar_click()
        # --- FIM DA MODIFICAÇÃO ---
        
        btn_export = ttk.Button(form_frame, text="Gerar PDF", style='TButton'); 
        btn_export.pack(pady=20)
@ -2876,16 +3028,12 @@ class App:
            matricula = selection.split(" - ")[0]; 
            nome_func = " ".join(selection.split(" - ")[1:])
            
            # --- MODIFICAÇÃO: Lendo do DateRangePicker ---
            start_dt, end_dt = date_picker.get_dates()
            # --- FIM DA MODIFICAÇÃO ---

            try:
                # --- MODIFICAÇÃO: Validação das novas datas ---
                if not start_dt or not end_dt:
                    messagebox.showerror("Erro", "Selecione um período válido (Início e Fim).", parent=win)
                    return
                # --- FIM DA MODIFICAÇÃO ---
                
                if end_dt < start_dt:
                    messagebox.showerror("Erro", "Data final não pode ser anterior à data inicial.", parent=win)
@ -2905,7 +3053,7 @@ class App:
                defaultextension=".pdf", 
                filetypes=[("PDF files", "*.pdf")], 
                title="Salvar Relatório", 
                initialfile=f"Log_{nome_func.replace(' ','_')}_{start_dt.isoformat()}_a_{end_dt.isoformat()}.pdf" # Nome do arquivo atualizado
                initialfile=f"Log_{nome_func.replace(' ','_')}_{start_dt.isoformat()}_a_{end_dt.isoformat()}.pdf"
            )
            if not filepath: 
                return
@ -2915,7 +3063,6 @@ class App:
                styles = getSampleStyleSheet(); 
                story = []
                
                # --- MODIFICAÇÃO: Estilos para quebra de linha ---
                style_table_header = ParagraphStyle(
                    name='TableHeader',
                    parent=styles['Normal'],
@ -2937,7 +3084,6 @@ class App:
                    textColor=colors.black,
                    alignment=TA_CENTER
                )
                # --- FIM DA MODIFICAÇÃO ---
                
                story.append(Paragraph("Relatório Log Alterações", styles['h1'])); 
                story.append(Spacer(1, 0.5*cm)); 
@ -2946,7 +3092,6 @@ class App:
                story.append(Paragraph(f"<b>Período:</b> {start_dt.strftime('%d/%m/%Y')} a {end_dt.strftime('%d/%m/%Y')}", styles['Normal'])); 
                story.append(Spacer(1, 1*cm))
                
                # --- MODIFICAÇÃO: Usando Paragraphs ---
                col_headers = ['Data Ponto', 'Data Edição', 'Valor Antigo', 'Valor Novo', 'Justificativa']
                table_data = [[Paragraph(h, style_table_header) for h in col_headers]]
                
@ -2959,7 +3104,6 @@ class App:
                        Paragraph(log['justificativa'], style_cell_center)
                    ]
                    table_data.append(row)
                # --- FIM DA MODIFICAÇÃO ---
                
                t = Table(table_data, colWidths=[2.5*cm, 3.0*cm, 8.0*cm, 8.0*cm, 4.0*cm]); 
                t.setStyle(TableStyle([
@ -2970,7 +3114,7 @@ class App:
                    ('BOTTOMPADDING', (0,0), (-1,0), 12), 
                    ('BACKGROUND', (0,1), (-1,-1), colors.beige), 
                    ('GRID', (0,0), (-1,-1), 1, colors.black),
                    ('VALIGN', (0,0), (-1,-1), 'TOP') # Alinha ao topo para melhor leitura
                    ('VALIGN', (0,0), (-1,-1), 'TOP')
                ]))
                story.append(t); 
                doc.build(story); 
@ -3645,45 +3789,54 @@ class App:

    def on_recalculate_and_refresh(self):
        """
        Força o recálculo do saldo para o(s) funcionário(s) selecionado(s)
        e depois atualiza o panorama.
        Força o reprocessamento dos dias e depois o recálculo do saldo.
        """
        self.append_log("Iniciando recálculo manual de saldos...")
        self.append_log("Iniciando reprocessamento completo...")
        target_matricula_str = self.cmb_filter_func.get()
        recalc_errors = 0

        if target_matricula_str == "Todos":
            if not messagebox.askyesno("Confirmar Recálculo Total", "Isso irá recalcular o saldo para TODOS os funcionários. Pode demorar.\n\nDeseja continuar?"):
                self.append_log("Recálculo cancelado pelo usuário.")
            if not messagebox.askyesno("Confirmar Recálculo Total", "Isso irá reprocessar TODOS os dias de TODOS os funcionários.\nIsso pode demorar alguns segundos.\n\nDeseja continuar?"):
                self.append_log("Cancelado pelo usuário.")
                return
            all_employees = self.db.get_all_funcionarios()
            self.append_log(f"Recalculando {len(all_employees)} funcionários...")
            self.append_log(f"Processando {len(all_employees)} funcionários...")
            for emp in all_employees:
                try:
                    # 1. Reprocessa os dias (corrige carga horária diária)
                    self.db.reprocess_daily_data(emp['matricula'])
                    # 2. Recalcula o saldo total (soma os novos dias)
                    self.db.recalculate_full_balance_for_employee(emp['matricula'])
                except Exception as e:
                   self.append_log(f"ERRO ao recalcular saldo para {emp['matricula']}: {e}")
                   self.append_log(f"ERRO em {emp['matricula']}: {e}")
                   recalc_errors += 1
        else:
            try:
                target_matricula = target_matricula_str.split(" - ")[0]
                self.append_log(f"Recalculando saldo para {target_matricula_str}...")
                self.append_log(f"Reprocessando dias de {target_matricula_str}...")
                
                # 1. Reprocessa os dias (corrige carga horária diária - ex: chegada cedo)
                self.db.reprocess_daily_data(target_matricula)
                
                self.append_log(f"Recalculando saldo total de {target_matricula_str}...")
                # 2. Recalcula o saldo total
                self.db.recalculate_full_balance_for_employee(target_matricula)
                
            except IndexError:
                self.append_log("ERRO: Nenhum funcionário selecionado para recalcular.")
                self.append_log("ERRO: Nenhum funcionário selecionado.")
                recalc_errors += 1
            except Exception as e:
                self.append_log(f"ERRO ao recalcular saldo para {target_matricula}: {e}")
                self.append_log(f"ERRO geral: {e}")
                recalc_errors += 1

        if recalc_errors == 0:
            self.append_log("Recálculo concluído com sucesso.")
            messagebox.showinfo("Concluído", "Saldos recalculados e panorama atualizado.")
            self.append_log("Processo concluído com sucesso.")
            messagebox.showinfo("Concluído", "Dias reprocessados e saldos atualizados com sucesso!")
        else:
             self.append_log(f"Recálculo concluído com {recalc_errors} erro(s).")
             messagebox.showwarning("Atenção", f"Recálculo concluído com {recalc_errors} erro(s). Verifique o log.")
             self.append_log(f"Concluído com {recalc_errors} erro(s).")
             messagebox.showwarning("Atenção", "Ocorreram erros durante o processo. Verifique o log.")

        # Agora, atualiza a visualização
        # Atualiza a visualização
        self.load_point_viewer(force_reload=True)
        self._update_calendar_tags()

@ -3706,11 +3859,10 @@ class App:
        action_button_frame.pack(side=tk.RIGHT)

        ttk.Button(action_button_frame, text="Recalcular e Atualizar", command=self.on_recalculate_and_refresh).pack(side=tk.LEFT, padx=5)

        ttk.Button(action_button_frame, text="📄 Exportar Ponto", command=self.on_export_panorama).pack(side=tk.LEFT, padx=5)

        ttk.Button(action_button_frame, text="💾 Salvar", command=self.commit_all_changes).pack(side=tk.LEFT, padx=5)

        # Calendário
        calendar_frame = tk.Frame(frame_viewer, bg="#0a192f")
        calendar_frame.grid(row=1, column=0, sticky="ew", pady=5, padx=10)
        calendar_frame.grid_columnconfigure(1, weight=1)
@ -3726,62 +3878,54 @@ class App:
                                      background="#008080", foreground="white", headersbackground="#008080",
                                      normalbackground="#112240", weekendbackground="#172a45",
                                      othermonthbackground="#0a192f", othermonthforeground="#6a7b9d",
                                      selectbackground=self.ACCENT_COLOR,
                                      mindate=min_date)
                                      selectbackground=self.ACCENT_COLOR, mindate=min_date)

        self.main_calendar.grid(row=0, column=0, rowspan=2, padx=(0, 20), sticky='n')
        self.main_calendar.bind("<<CalendarSelected>>", self.on_calendar_click)
        self.main_calendar.bind("<<CalendarMonthChanged>>", self.on_calendar_month_changed)

        
        # Tags do calendário
        self.main_calendar.tag_config('start_date', background=self.START_DATE_COLOR, foreground='white')
        self.main_calendar.tag_config('end_date', background=self.END_DATE_COLOR, foreground='white')
        self.main_calendar.tag_config('range_date', background=self.RANGE_BG_COLOR, foreground='#ccd6f6')
        self.main_calendar.tag_config('holiday', background=self.HOLIDAY_COLOR, foreground='white')

        # Labels de Período
        period_frame = tk.Frame(calendar_frame, bg="#0a192f")
        period_frame.grid(row=0, column=1, columnspan=2, sticky='nw', padx=5)

        tk.Label(period_frame, text="Período:", bg="#0a192f", fg="#ccd6f6", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        start_frame = tk.Frame(period_frame, bg="#0a192f")
        start_frame.pack(anchor='w', pady=2)
        start_frame = tk.Frame(period_frame, bg="#0a192f"); start_frame.pack(anchor='w', pady=2)
        tk.Label(start_frame, text="Início:", bg="#0a1f2f", fg="#ccd6f6", width=5, anchor='w').pack(side=tk.LEFT)
        self.lbl_selected_start = tk.Label(start_frame, text="--/--/----", bg="#0a192f", fg="white", font=('Segoe UI', 10, 'bold'), width=12, anchor='w')
        self.lbl_selected_start.pack(side=tk.LEFT)

        end_frame = tk.Frame(period_frame, bg="#0a192f")
        end_frame.pack(anchor='w', pady=2)
        end_frame = tk.Frame(period_frame, bg="#0a192f"); end_frame.pack(anchor='w', pady=2)
        tk.Label(end_frame, text="Fim:", bg="#0a192f", fg="#ccd6f6", width=5, anchor='w').pack(side=tk.LEFT)
        self.lbl_selected_end = tk.Label(end_frame, text="--/--/----", bg="#0a192f", fg="white", font=('Segoe UI', 10, 'bold'), width=12, anchor='w')
        self.lbl_selected_end.pack(side=tk.LEFT)

        # Listas de Feriados e Punições
        holiday_frame = tk.Frame(calendar_frame, bg=self.BG_COLOR)
        holiday_frame.grid(row=1, column=1, sticky='nsew', padx=5, pady=(10,0))
        tk.Label(holiday_frame, text="Feriados:", bg="#0a192f", fg="#ccd6f6", font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 2))
        holiday_list_frame = tk.Frame(holiday_frame, bg=self.BG_COLOR)
        holiday_list_frame.pack(fill=tk.BOTH, expand=True)
        holiday_scrollbar = ttk.Scrollbar(holiday_list_frame, orient=tk.VERTICAL)
        self.holiday_listbox = tk.Listbox(holiday_list_frame, yscrollcommand=holiday_scrollbar.set, bg=self.LIGHT_BG, fg=self.FG_COLOR, selectbackground=self.ACCENT_COLOR, selectforeground=self.FG_COLOR, borderwidth=0, highlightthickness=0, activestyle='none', height=3)
        holiday_scrollbar.config(command=self.holiday_listbox.yview)
        holiday_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        holiday_list_frame = tk.Frame(holiday_frame, bg=self.BG_COLOR); holiday_list_frame.pack(fill=tk.BOTH, expand=True)
        self.holiday_listbox = tk.Listbox(holiday_list_frame, bg=self.LIGHT_BG, fg=self.FG_COLOR, height=3)
        self.holiday_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        punishment_frame = tk.Frame(calendar_frame, bg=self.BG_COLOR)
        punishment_frame.grid(row=1, column=2, sticky='nsew', padx=5, pady=(10,0))
        tk.Label(punishment_frame, text="Punições:", bg="#0a192f", fg="#ccd6f6", font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 2))
        punishment_list_frame = tk.Frame(punishment_frame, bg=self.BG_COLOR)
        punishment_list_frame.pack(fill=tk.BOTH, expand=True)
        punishment_scrollbar = ttk.Scrollbar(punishment_list_frame, orient=tk.VERTICAL)
        self.punishment_listbox = tk.Listbox(punishment_list_frame, yscrollcommand=punishment_scrollbar.set, bg=self.LIGHT_BG, fg=self.FG_COLOR, selectbackground=self.ACCENT_COLOR, selectforeground=self.FG_COLOR, borderwidth=0, highlightthickness=0, activestyle='none', height=3)
        punishment_scrollbar.config(command=self.punishment_listbox.yview)
        punishment_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        punishment_list_frame = tk.Frame(punishment_frame, bg=self.BG_COLOR); punishment_list_frame.pack(fill=tk.BOTH, expand=True)
        self.punishment_listbox = tk.Listbox(punishment_list_frame, bg=self.LIGHT_BG, fg=self.FG_COLOR, height=3)
        self.punishment_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.lbl_total_punishments = tk.Label(punishment_frame, text="Total Punições: --", bg="#0a192f", fg=self.FG_COLOR, font=('Segoe UI', 9))
        self.lbl_total_punishments.pack(anchor='w', pady=(2, 0))

        # Labels de Saldos
        frame_saldos = ttk.LabelFrame(frame_viewer, text=" Saldos Atuais", style='TLabelframe')
        frame_saldos.grid(row=2, column=0, sticky="ew", pady=(10, 5), padx=10)
        tk.Label(frame_saldos, text="BH:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT, padx=(10,0)); self.lbl_saldo_bh_total = tk.Label(frame_saldos, text="--:--:--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=15, anchor="w"); self.lbl_saldo_bh_total.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Extras:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_saldo_extras_total = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=10, anchor="w"); self.lbl_saldo_extras_total.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Fichado:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_fichado_status = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=10, anchor="w"); self.lbl_fichado_status.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Setor:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_setor_status = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=15, anchor="w"); self.lbl_setor_status.pack(side=tk.LEFT, padx=5)

        # Treeview (Tabela)
        tree_frame = tk.Frame(frame_viewer, bg="#0a192f");
        tree_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)
        tree_frame.grid_rowconfigure(0, weight=1)
@ -3796,20 +3940,23 @@ class App:
        v_scroll.grid(row=0, column=1, sticky='ns')
        h_scroll.grid(row=1, column=0, sticky='ew')

        # --- AQUI ESTÁ A CORREÇÃO: CRIAÇÃO DO MENU DEPOIS DA TREEVIEW ---
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Desconsiderar Atraso (Alternar)", command=self.toggle_ignore_delay_context)
        self.tree_viewer.bind("<Button-3>", self.show_context_menu)
        # -------------------------------------------------------------

        col_widths = {"Matrícula": 80, "Nome": 220, "Data": 80, "E1": 60, "S1": 60, "E2": 60, "S2": 60, "Carga_Horaria": 90, "Punição": 80, "Total_Desconto": 100}
        for col in columns:
            anchor = tk.W if col == "Nome" else tk.CENTER
            self.tree_viewer.heading(col, text=col.replace('_', ' ').replace('Carga Horaria', 'Carga Horária'))
            self.tree_viewer.column(col, width=col_widths.get(col, 100), anchor=anchor, stretch=tk.NO)
            self.tree_viewer.heading(col, text=col.replace('_', ' '))
            self.tree_viewer.column(col, width=col_widths.get(col, 100))

        self.tree_viewer.bind('<ButtonRelease-1>', self.start_in_place_edit)
        self.tree_viewer.tag_configure('evenrow', background='#112240')
        self.tree_viewer.tag_configure('oddrow', background='#172a45')
        self.tree_viewer.tag_configure('incomplete', foreground='#FF6B6B') # Vermelho

        self.tree_viewer.tag_configure('incomplete', foreground='#FF6B6B')

        self.update_employee_filter()
        self._update_calendar_tags()


    def on_calendar_month_changed(self, event=None): self._update_calendar_tags()
