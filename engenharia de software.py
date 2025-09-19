programa PontoEletronico

// Declaração de Estruturas de Dados
tipo Funcionario é registro
    id: inteiro
    nome: texto
fim_registro

tipo RegistroPonto é registro
    id_registro: inteiro
    id_funcionario: inteiro
    data: data
    hora_entrada: horario
    hora_saida: horario
    horas_trabalhadas: real
    atraso_penalizado_minutos: inteiro
    extras_concedidas: real // Pode ser em horas ou em folgas
fim_registro

// Declaração de Variáveis Globais
bancoDeDados: SQLite_DB // Representação do banco de dados SQLite


-------------------------------------------------------------------------------------------------------


modulo interface_grafica
    
    // Procedimento Principal da Interface
    procedimento exibir_tela_principal()
        exibir_janela("Controle de Ponto")
        
        // Componentes da Interface
        criar_campo_texto("Filtro por Data")
        criar_botao("Importar Ponto de TXT", ao_clicar_importar)
        criar_lista_exibicao("Folha de Ponto")
        
        // Adicionando uma coluna para o status de ponto
        adicionar_coluna_na_lista("Nome", "Data", "Entrada", "Saída", "Horas", "Status")
        
        // Exibir a lista de funcionários com status
        listar_funcionarios_e_status_ponto()
        
    fim_procedimento

    // Procedimento para o Botão "Importar"
    procedimento ao_clicar_importar()
        caminho_arquivo = abrir_dialogo_arquivo()
        se caminho_arquivo existe então
            processar_dados_txt(caminho_arquivo)
            atualizar_lista_exibicao()
            exibir_mensagem_sucesso("Importação concluída!")
        fim_se
    fim_procedimento
    
    // Procedimento para Gerenciar Pontos Manuais e Extras
    procedimento ao_clicar_em_item_da_lista()
        registro_selecionado = obter_item_selecionado()
        
        se registro_selecionado.status == "Falta de Ponto" então
            exibir_janela_insercao_manual(registro_selecionado.nome, registro_selecionado.data)
            se usuario_inseriu_dados() então
                hora_entrada = obter_entrada_digitada()
                hora_saida = obter_saida_digitada()
                
                salvar_ponto_manual(registro_selecionado.id_func, registro_selecionado.data, hora_entrada, hora_saida)
                atualizar_lista_exibicao()
            fim_se
        fim_se
        
        se registro_selecionado.horas_extras_calculadas > 0 então
            exibir_janela_controle_extras(registro_selecionado.id_func, registro_selecionado.horas_extras_calculadas)
            se usuario_confirmou_concessao() então
                registrar_concessao_extra(registro_selecionado.id_func, "pagamento" ou "folga")
                atualizar_lista_exibicao()
            fim_se
        fim_se
    fim_procedimento

fim_modulo

------------------------------------------------------------------------------------------------------------------------------------------------
modulo processamento_de_dados
    
    procedimento processar_dados_txt(caminho_arquivo)
        abrir_arquivo(caminho_arquivo)
        
        // Dicionário temporário para agrupar pontos por funcionário e dia
        pontos_por_dia: dicionario (chave: (nome, data), valor: lista de horários)
        
        // Ler e agrupar os pontos do arquivo
        para cada linha no arquivo
            se linha não é cabeçalho então
                partes = dividir_linha(linha, '\t')
                nome = partes[3]
                data_e_hora_texto = partes[6] + " " + partes[7]
                data_e_hora_obj = converter_texto_para_data_e_hora(data_e_hora_texto)
                
                chave = (nome, data_de(data_e_hora_obj))
                se chave não está em pontos_por_dia então
                    pontos_por_dia[chave] = lista_vazia
                fim_se
                
                adicionar_a_lista(pontos_por_dia[chave], hora_de(data_e_hora_obj))
            fim_se
        fim_para
        
        // Tratar os dados agrupados e inserir no banco
        para cada (nome, data), lista_de_horarios em pontos_por_dia
            se tamanho_da_lista(lista_de_horarios) >= 2 então
                hora_entrada_real = primeiro_horario(lista_de_horarios)
                hora_saida_real = ultimo_horario(lista_de_horarios)
                
                // Lógica de negócio
                horas_trabalhadas = calcular_horas_trabalhadas(hora_entrada_real, hora_saida_real)
                atraso_penalizado = calcular_atraso(hora_entrada_real)
                
                // Insere no banco com os dados tratados
                id_func = obter_id_ou_inserir_funcionario(nome)
                inserir_registro_ponto(id_func, data, hora_entrada_real, hora_saida_real, horas_trabalhadas, atraso_penalizado)
            senão
                // Funcionario com ponto incompleto
                id_func = obter_id_ou_inserir_funcionario(nome)
                inserir_registro_ponto(id_func, data, NULO, NULO, NULO, NULO)
            fim_se
        fim_para
    fim_procedimento
    
    funcao calcular_horas_trabalhadas(entrada, saida): real
        // Assumir 1 hora de almoço padrão, ou permitir flexibilidade com 4 batidas.
        // Aqui a lógica completa para calcular a carga horária, incluindo o almoço.
        retornar horas_trabalhadas_calculadas
    fim_funcao
    
    funcao calcular_atraso(hora_entrada): inteiro
        hora_inicio_expediente = '07:30' ou '13:00'
        diferenca_em_minutos = diferenca_entre_horarios(hora_entrada, hora_inicio_expediente)
        
        se diferenca_em_minutos <= 5 então
            retornar 0 // Tolerância de 5 minutos
        senão se diferenca_em_minutos <= 10 então
            retornar diferenca_em_minutos * 2
        senão se diferenca_em_minutos <= 15 então
            retornar diferenca_em_minutos * 3
        senão
            retornar 0 // Atraso acima de 15 minutos não é penalizado no cálculo
        fim_se
    fim_funcao
    
    procedimento calcular_e_registrar_extras_semanais()
        para cada funcionario
            semana = obter_semana_atual()
            horas_totais = somar_horas_por_semana(funcionario, semana)
            
            se horas_totais > 44 então
                extras_a_conceder = (horas_totais - 44) / 4
                // Registrar no banco de dados para controle
                registrar_extras(funcionario, semana, extras_a_conceder)
            fim_se
        fim_para
    fim_procedimento
    
fim_modulo


-------------------------------------------------------------------------------------------------------------------------------------------

modulo banco_de_dados
    
    procedimento conectar_ou_criar()
        conectar_ao_arquivo("ponto.db")
        criar_tabelas() // Garante que as tabelas existem
    fim_procedimento
    
    procedimento criar_tabelas()
        executar_SQL("CREATE TABLE IF NOT EXISTS funcionarios...")
        executar_SQL("CREATE TABLE IF NOT EXISTS pontos...")
        // Adicionar tabela para controle de horas extras
        executar_SQL("CREATE TABLE IF NOT EXISTS extras (id_func, data_semana, horas_extras, status)")
    fim_procedimento
    
    funcao obter_id_ou_inserir_funcionario(nome): inteiro
        id = buscar_funcionario_por_nome(nome)
        se id não existe então
            id = inserir_novo_funcionario(nome)
        fim_se
        retornar id
    fim_funcao
    
    procedimento inserir_registro_ponto(id_func, data, entrada, saida, horas_trab, atraso)
        executar_SQL("INSERT INTO pontos (...) VALUES (...)")
    fim_procedimento
    
    procedimento atualizar_ponto(id_registro, nova_entrada, nova_saida)
        executar_SQL("UPDATE pontos SET entrada=?, saida=? WHERE id=?", nova_entrada, nova_saida, id_registro)
    fim_procedimento
    
    procedimento registrar_extras(id_func, semana, horas_extras)
        executar_SQL("INSERT INTO extras (...) VALUES (...)")
    fim_procedimento

    funcao buscar_pontos_por_data(data): lista_de_registros
        executar_SQL("SELECT * FROM pontos WHERE data = ?", data)
        retornar resultado
    fim_funcao
    
fim_modulo