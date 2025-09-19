modulo
interface_grafica

// Procedimento
Principal
da
Interface
procedimento
exibir_tela_principal()
exibir_janela("Controle de Ponto")

// Componentes
da
Interface
criar_campo_texto("Filtro por Data")
criar_botao("Importar Ponto de TXT", ao_clicar_importar)
criar_lista_exibicao("Folha de Ponto")

// Adicionando
uma
coluna
para
o
status
de
ponto
adicionar_coluna_na_lista("Nome", "Data", "Entrada", "Saída", "Horas", "Status")

// Exibir
a
lista
de
funcionários
com
status
listar_funcionarios_e_status_ponto()

fim_procedimento

// Procedimento
para
o
Botão
"Importar"
procedimento
ao_clicar_importar()
caminho_arquivo = abrir_dialogo_arquivo()
se
caminho_arquivo
existe
então
processar_dados_txt(caminho_arquivo)
atualizar_lista_exibicao()
exibir_mensagem_sucesso("Importação concluída!")
fim_se
fim_procedimento

// Procedimento
para
Gerenciar
Pontos
Manuais
e
Extras
procedimento
ao_clicar_em_item_da_lista()
registro_selecionado = obter_item_selecionado()

se
registro_selecionado.status == "Falta de Ponto"
então
exibir_janela_insercao_manual(registro_selecionado.nome, registro_selecionado.data)
se
usuario_inseriu_dados()
então
hora_entrada = obter_entrada_digitada()
hora_saida = obter_saida_digitada()

salvar_ponto_manual(registro_selecionado.id_func, registro_selecionado.data, hora_entrada, hora_saida)
atualizar_lista_exibicao()
fim_se
fim_se

se
registro_selecionado.horas_extras_calculadas > 0
então
exibir_janela_controle_extras(registro_selecionado.id_func, registro_selecionado.horas_extras_calculadas)
se
usuario_confirmou_concessao()
então
registrar_concessao_extra(registro_selecionado.id_func, "pagamento"
ou
"folga")
atualizar_lista_exibicao()
fim_se
fim_se
fim_procedimento

fim_modulo