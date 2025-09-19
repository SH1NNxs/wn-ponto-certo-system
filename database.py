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


