
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import sqlite3
import json
from datetime import datetime
from reportlab.pdfgen import canvas

DB = "ponto.db"
SYSTEM_START_DATE = "2026-01-01"

def safe_json_load(data):
    try:
        return json.loads(data) if isinstance(data, str) else data
    except:
        return []

def minutos_para_hhmm(mins):
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("WN Ponto Certo v3 - Auditoria RH")
        self.root.state("zoomed")

        self.conn = sqlite3.connect(DB)
        self.cursor = self.conn.cursor()

        self.funcionario_filtro = tk.StringVar()

        self.build_ui()
        self.carregar_funcionarios()

    def build_ui(self):
        self.root.configure(bg="#0a192f")

        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        top = tk.Frame(self.root, bg="#112240")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)

        ttk.Label(top, text="Funcionário:", background="#112240", foreground="white").grid(row=0, column=0)
        self.combo = ttk.Combobox(top, textvariable=self.funcionario_filtro)
        self.combo.grid(row=0, column=1, sticky="ew")
        self.combo.bind("<<ComboboxSelected>>", lambda e: self.atualizar())

        btn = ttk.Button(top, text="Importar TXT", command=self.importar_txt)
        btn.grid(row=0, column=2)

        self.tree = ttk.Treeview(self.root, columns=("data","e1","s1","e2","s2","carga"), show="headings")
        for c in self.tree["columns"]:
            self.tree.heading(c, text=c.upper())

        self.tree.grid(row=1, column=0, sticky="nsew")

    def carregar_funcionarios(self):
        self.cursor.execute("SELECT matricula, nome FROM funcionarios")
        dados = self.cursor.fetchall()
        self.combo["values"] = [f"{m} - {n}" for m,n in dados]

    def importar_txt(self):
        file = filedialog.askopenfilename()
        if not file:
            return

        novos = []

        with open(file) as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                matricula = parts[2]
                nome = parts[3]

                self.cursor.execute("SELECT 1 FROM funcionarios WHERE matricula=?", (matricula,))
                if not self.cursor.fetchone():
                    novos.append((matricula,nome))

        if novos:
            for m,n in novos:
                self.cadastrar_funcionario(m,n)
            return

        messagebox.showinfo("OK","Importação concluída")

    def cadastrar_funcionario(self, matricula, nome):
        win = tk.Toplevel(self.root)
        win.title("Cadastro obrigatório")

        setor = tk.StringVar()
        fichado = tk.StringVar()
        bh = tk.StringVar()
        extras = tk.StringVar()

        ttk.Label(win, text=f"{matricula} - {nome}").grid()

        ttk.Label(win, text="Setor").grid()
        ttk.Combobox(win, textvariable=setor, values=["Administrativo","Operacional"]).grid()

        ttk.Label(win, text="Fichado").grid()
        ttk.Combobox(win, textvariable=fichado, values=["Sim","Não"]).grid()

        ttk.Label(win, text="BH Inicial (HH:MM)").grid()
        ttk.Entry(win, textvariable=bh).grid()

        ttk.Label(win, text="Extras Iniciais").grid()
        ttk.Entry(win, textvariable=extras).grid()

        def salvar():
            h,m = map(int,bh.get().split(":"))
            bh_min = h*60+m

            self.cursor.execute("""
            INSERT INTO funcionarios (matricula,nome,setor,fichado,bh_inicial,extras_iniciais,bh_atual,extras_atuais)
            VALUES (?,?,?,?,?,?,?,?)
            """,(matricula,nome,setor.get(),fichado.get(),bh_min,int(extras.get()),bh_min,int(extras.get())))
            self.conn.commit()
            win.destroy()
            self.carregar_funcionarios()

        ttk.Button(win,text="Salvar",command=salvar).grid()

    def atualizar(self):
        self.tree.delete(*self.tree.get_children())
        sel = self.funcionario_filtro.get().split(" - ")[0]

        self.cursor.execute("SELECT data, periodos, minutos_totais FROM horas_trabalhadas WHERE matricula=?", (sel,))
        for data,periodos,mins in self.cursor.fetchall():
            p = safe_json_load(periodos)
            e1 = p[0] if len(p)>0 else ""
            s1 = p[1] if len(p)>1 else ""
            e2 = p[2] if len(p)>2 else ""
            s2 = p[3] if len(p)>3 else ""

            self.tree.insert("", "end", values=(data,e1,s1,e2,s2,minutos_para_hhmm(mins)))

root = tk.Tk()
app = App(root)
root.mainloop()
