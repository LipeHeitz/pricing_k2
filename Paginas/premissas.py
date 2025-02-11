import streamlit as st
import pandas as pd
import numpy as np
import numpy_financial as npf
from scipy.optimize import root_scalar
import math


# Função para formatar no padrão brasileiro (arredondando para cima)
def formatar_brasileiro(valor):
    if isinstance(valor, (int, float)):
        # Arredondando para cima
        valor = math.ceil(valor * 100) / 100  # Garante que arredonde sempre para cima
        # Convertendo para string no formato correto (ponto nos milhares e vírgula nos decimais)
        return "{:,.2f}".format(valor).replace(",", "X").replace(".", ",").replace("X", ".")
    return valor

def simular_emprestimo(valor_emprestado, num_parcelas, tir_desejada, inflacao_anual,
                        aliquota_pis, aliquota_cofins,
                        tipo_operacao="aluguel",  # "aluguel" ou "compra"
                        pmt_min=None, pmt_max=None, n_points=101,
                        aliquota_irpj=0.15, aliquota_cssl=0.09,
                        limite_isencao_irpj=60000, aliquota_adicional_irpj=0.10):
    """
    Simula um empréstimo considerando dois tipos de operação: "aluguel" (aluguel) ou "compra".
    
    Para "aluguel":
      - Nos períodos tributáveis (meses m em que m ≥ 4 e (m-1)%3==0), a base para IRPJ e CSSL é
        calculada como 32% da soma dos 3 fluxos brutos anteriores, EXCETO para o último período
        tributável e para o fluxo extra final, que usarão os novos fatores:
          • Base IRPJ = 8%
          • Base CSSL = 12%
      - O fluxo extra final é inserido no próximo período tributável após o último fluxo normal.
      
    Para "compra":
      - Para os meses de 1 até num_parcelas-1 utiliza-se o fator 0.32;
      - Apenas no último fluxo normal (mês num_parcelas) e no fluxo extra (imediatamente após)
        serão usados os novos fatores: 8% para IRPJ e 12% para CSSL.
        
    Em ambos os casos, se a base IRPJ (calculada com o fator aplicável) for ≥ 60.000,
    a base adicional é definida como (base IRPJ – 60.000) e incide uma alíquota adicional (aliquota_adicional_irpj).
    
    Retorna:
      - pmt_otimizada: a maior PMT que resulta na TIR desejada.
      - fluxo_bruta: lista dos fluxos brutos.
      - fluxo_liquida: lista dos fluxos líquidos (com todos os custos incorporados).
      - df_fluxos: DataFrame com os fluxos e os custos detalhados.
    """
    # Determina os períodos tributáveis (meses em que há cobrança de CSSL/IRPJ) conforme regra trimestral:
    impostos_meses = [mes for mes in range(4, num_parcelas + 1) if (mes - 1) % 3 == 0]
    
    # Para operação de locação, o fluxo extra final será inserido no próximo período tributável após o último fluxo normal.
    if tipo_operacao.lower() == "compra":
        m = num_parcelas + 1
        while True:
            if m >= 4 and (m - 1) % 3 == 0:
                extra_index = m
                break
            m += 1
    elif tipo_operacao.lower() == "aluguel":
        extra_index = num_parcelas + 1
    else:
        raise ValueError("Tipo de operação inválido. Use 'aluguel' ou 'compra'.")

    # Cálculo da PMT teórica sem custos (fórmula PRICE; npf.pmt usa PV negativo).
    pmt_teorica = abs(npf.pmt(tir_desejada, num_parcelas, valor_emprestado))
    if pmt_min is None:
        pmt_min = pmt_teorica
    if pmt_max is None:
        pmt_max = pmt_teorica * 2

    def calcular_fluxos_com_impostos(pmt_bruta):
        total_fluxos = extra_index + 1  # índices 0 até extra_index (inclusive)
        fluxo_bruta = [0] * total_fluxos
        fluxo_liquida = [0] * total_fluxos

        # Arrays para armazenar os custos detalhados (para o DataFrame)
        custos_pis = [0] * total_fluxos
        custos_cofins = [0] * total_fluxos
        custos_cssl = [0] * total_fluxos
        custos_irpj = [0] * total_fluxos
        bases_irpj = [0] * total_fluxos
        bases_adicional_irpj = [0] * total_fluxos

        # Mês 0: investimento negativo
        fluxo_bruta[0] = -valor_emprestado
        fluxo_liquida[0] = -valor_emprestado

        pmt_atual = pmt_bruta
        for mes in range(1, num_parcelas + 1):
            if mes > 1 and (mes - 1) % 12 == 0:
                pmt_atual *= (1 + inflacao_anual)
            fluxo_bruta[mes] = pmt_atual
            # Custos de PIS e COFINS
            custo_pis = - (pmt_atual * aliquota_pis)
            custo_cofins = - (pmt_atual * aliquota_cofins)
            custos_pis[mes] = custo_pis
            custos_cofins[mes] = custo_cofins

            # Define os fatores para o cálculo da base:
            if tipo_operacao.lower() == "aluguel":
                # Se mes for tributável, para locação:
                # Se este é o último período tributável (ou seja, mes == max(impostos_meses)), usar os novos fatores;
                # caso contrário, usar 0.32.
                if mes in impostos_meses:
                    if mes == max(impostos_meses):
                        factor_irpj = 0.32
                        factor_cssl = 0.32
                    else:
                        factor_irpj = 0.32
                        factor_cssl = 0.32
                else:
                    factor_irpj = 0.0
                    factor_cssl = 0.0
            else:  # compra
                if mes in impostos_meses:
                    if mes < num_parcelas:
                        factor_irpj = 0.32
                        factor_cssl = 0.32
                    else:
                        factor_irpj = 0.08
                        factor_cssl = 0.12
                else:
                    factor_irpj = 0.0
                    factor_cssl = 0.0

            if mes in impostos_meses:
                base_cssl = sum(fluxo_bruta[mes - 3: mes]) * factor_cssl
                custo_cssl = - (base_cssl * aliquota_cssl)
                base_irpj = sum(fluxo_bruta[mes - 3: mes]) * factor_irpj
                if base_irpj >= limite_isencao_irpj:
                    base_adicional = base_irpj - limite_isencao_irpj
                else:
                    base_adicional = 0
                custo_irpj = - (base_irpj * aliquota_irpj + base_adicional * aliquota_adicional_irpj)
            else:
                custo_cssl = 0.0
                custo_irpj = 0.0
                base_irpj = 0.0
                base_adicional = 0.0

            custos_cssl[mes] = custo_cssl
            custos_irpj[mes] = custo_irpj
            bases_irpj[mes] = base_irpj
            bases_adicional_irpj[mes] = base_adicional

            fluxo_liquida[mes] = fluxo_bruta[mes] + custo_pis + custo_cofins + custo_cssl + custo_irpj

        # Para os meses entre o último fluxo normal e o fluxo extra, preenche com 0.
        for mes in range(num_parcelas + 1, extra_index):
            fluxo_bruta[mes] = 0
            fluxo_liquida[mes] = 0
            custos_pis[mes] = 0
            custos_cofins[mes] = 0
            custos_cssl[mes] = 0
            custos_irpj[mes] = 0
            bases_irpj[mes] = 0
            bases_adicional_irpj[mes] = 0

        # Fluxo extra final (índice extra_index):
        if num_parcelas >= 3:
            if tipo_operacao.lower() == "aluguel":
            # Para o fluxo extra, agora usamos os últimos 3 meses anteriores ao extra_index:
                base_cssl_final = sum(fluxo_bruta[extra_index - 3: extra_index]) * 0.32
                custo_cssl_final = - (base_cssl_final * aliquota_cssl)
                base_irpj_final = sum(fluxo_bruta[extra_index - 3: extra_index]) * 0.32
                if base_irpj_final >= limite_isencao_irpj:
                    base_adicional_final = base_irpj_final - limite_isencao_irpj
                else:
                    base_adicional_final = 0
                custo_irpj_final = - (base_irpj_final * aliquota_irpj + base_adicional_final * aliquota_adicional_irpj)
            else: # Compra
                # Para o fluxo extra, agora usamos os últimos 3 meses anteriores ao extra_index:
                base_cssl_final = sum(fluxo_bruta[extra_index - 3: extra_index]) * 0.12
                custo_cssl_final = - (base_cssl_final * aliquota_cssl)
                base_irpj_final = sum(fluxo_bruta[extra_index - 3: extra_index]) * 0.08
                if base_irpj_final >= limite_isencao_irpj:
                    base_adicional_final = base_irpj_final - limite_isencao_irpj
                else:
                    base_adicional_final = 0
                custo_irpj_final = - (base_irpj_final * aliquota_irpj + base_adicional_final * aliquota_adicional_irpj)
        else:
            custo_cssl_final = 0.0
            custo_irpj_final = 0.0
            base_irpj_final = 0.0
            base_adicional_final = 0.0

        fluxo_bruta[extra_index] = 0
        fluxo_liquida[extra_index] = custo_cssl_final + custo_irpj_final

        # Armazena os custos detalhados em um dicionário para o DataFrame
        custos = {
            "PIS": custos_pis,
            "COFINS": custos_cofins,
            "CSSL": custos_cssl,
            "IRPJ": custos_irpj,
            "Base_IRPJ": bases_irpj,
            "Base_Adicional_IRPJ": bases_adicional_irpj
        }
        custos["PIS"][extra_index] = 0
        custos["COFINS"][extra_index] = 0
        custos["CSSL"][extra_index] = custo_cssl_final
        custos["IRPJ"][extra_index] = custo_irpj_final
        custos["Base_IRPJ"][extra_index] = base_irpj_final
        custos["Base_Adicional_IRPJ"][extra_index] = base_adicional_final

        return fluxo_bruta, fluxo_liquida, custos

    def funcao_goal_seek_impostos(pmt_bruta):
        _, fluxos_liquidos, _ = calcular_fluxos_com_impostos(pmt_bruta)
        tir_liquida = npf.irr(fluxos_liquidos)
        if np.isnan(tir_liquida):
            return -1 - tir_desejada
        return tir_liquida - tir_desejada

    # --- Grid search para encontrar raízes da função objetivo ---
    pmt_grid = np.linspace(pmt_min, pmt_max, n_points)
    f_vals = [funcao_goal_seek_impostos(pmt) for pmt in pmt_grid]

    raizes = []
    for i in range(len(pmt_grid) - 1):
        if f_vals[i] * f_vals[i+1] < 0:
            bracket = [pmt_grid[i], pmt_grid[i+1]]
            try:
                sol = root_scalar(funcao_goal_seek_impostos, bracket=bracket, method="brentq")
                if sol.converged:
                    raizes.append(sol.root)
            except Exception:
                pass

    if raizes:
        pmt_otimizada = max(raizes)
    else:
        raise ValueError("Nenhuma solução encontrada para o PMT no intervalo definido.")

    fluxo_bruta, fluxo_liquida, custos = calcular_fluxos_com_impostos(pmt_otimizada)
    tir_final = npf.irr(fluxo_liquida)

    # --- Montagem do DataFrame para exibição ---
    meses = list(range(0, extra_index + 1))
    df_fluxos = pd.DataFrame({
        "Mês": meses,
        "Fluxo de Caixa Bruta": fluxo_bruta,
        "Fluxo de Caixa Líquida": fluxo_liquida
    })

    # Cálculo separado de PIS e COFINS para exibição
    df_fluxos["PIS"] = df_fluxos["Fluxo de Caixa Bruta"].apply(lambda x: - (x * aliquota_pis) if x > 0 else 0)
    df_fluxos["COFINS"] = df_fluxos["Fluxo de Caixa Bruta"].apply(lambda x: - (x * aliquota_cofins) if x > 0 else 0)

    # Acrescenta colunas para as bases e custos dos impostos (CSSL e IRPJ)
    df_fluxos["Base Tributável CSSL"] = 0.0
    df_fluxos["CSSL"] = 0.0
    df_fluxos["Base Tributável IRPJ"] = 0.0
    df_fluxos["Base Adicional IRPJ"] = 0.0
    df_fluxos["IRPJ"] = 0.0
    df_fluxos["IRPJ Adicional"] = 0.0

    for mes in impostos_meses:
        base_cssl = sum(df_fluxos.loc[mes - 3: mes - 1, "Fluxo de Caixa Bruta"])
        if tipo_operacao.lower() == "aluguel":
            if mes == max(impostos_meses):
                base_cssl *= 0.32
            else:
                base_cssl *= 0.32
        else: # compra
            if mes == max(impostos_meses):
                base_cssl *= 0.12
            else:
                base_cssl *= 0.32
        cssl_valor = - (base_cssl * aliquota_cssl)
        
        base_irpj = sum(df_fluxos.loc[mes - 3: mes - 1, "Fluxo de Caixa Bruta"])
        if tipo_operacao.lower() == "aluguel":
            if mes == max(impostos_meses):
                base_irpj *= 0.32
            else:
                base_irpj *= 0.32
        else: # compra
            if mes == max(impostos_meses):
                base_irpj *= 0.08
            else:
                base_irpj *= 0.32
        if base_irpj >= limite_isencao_irpj:
            base_adicional = base_irpj - limite_isencao_irpj
        else:
            base_adicional = 0
        irpj_basico = - (base_irpj * aliquota_irpj)
        irpj_adicional = - (base_adicional * aliquota_adicional_irpj)
        total_irpj = irpj_basico + irpj_adicional

        df_fluxos.loc[mes, "Base Tributável CSSL"] = base_cssl
        df_fluxos.loc[mes, "CSSL"] = cssl_valor
        df_fluxos.loc[mes, "Base Tributável IRPJ"] = base_irpj
        df_fluxos.loc[mes, "Base Adicional IRPJ"] = base_adicional
        df_fluxos.loc[mes, "IRPJ"] = total_irpj
        df_fluxos.loc[mes, "IRPJ Adicional"] = irpj_adicional

    if extra_index > max(impostos_meses):
        base_cssl_final = sum(df_fluxos.loc[extra_index - 3: extra_index, "Fluxo de Caixa Bruta"])
        if tipo_operacao.lower() == "aluguel":
            base_cssl_final *= 0.32
        else: # compra
            base_cssl_final *= 0.12
        cssl_final = - (base_cssl_final * aliquota_cssl)

        base_irpj_final = sum(df_fluxos.loc[extra_index - 3: extra_index, "Fluxo de Caixa Bruta"])
        if tipo_operacao.lower() == "aluguel":
            base_irpj_final *= 0.32
        else: # compra
            base_irpj_final *= 0.08
        if base_irpj_final >= limite_isencao_irpj:
            base_adicional_final = base_irpj_final - limite_isencao_irpj
        else:
            base_adicional_final = 0
        irpj_basico_final = - (base_irpj_final * aliquota_irpj)
        irpj_adicional_final = - (base_adicional_final * aliquota_adicional_irpj)
        total_irpj_final = irpj_basico_final + irpj_adicional_final

        df_fluxos.loc[extra_index, "Base Tributável CSSL"] = base_cssl_final
        df_fluxos.loc[extra_index, "CSSL"] = cssl_final
        df_fluxos.loc[extra_index, "Base Tributável IRPJ"] = base_irpj_final
        df_fluxos.loc[extra_index, "Base Adicional IRPJ"] = base_adicional_final
        df_fluxos.loc[extra_index, "IRPJ"] = total_irpj_final
        df_fluxos.loc[extra_index, "IRPJ Adicional"] = irpj_adicional_final

    return pmt_otimizada, fluxo_bruta, fluxo_liquida, df_fluxos

def app():
    if 'premissas' not in st.session_state or not st.session_state['premissas']:
        st.title("Configuração de Premissas")
        st.write("Insira os valores das premissas:")
        st.session_state['tipo_operacao'] = st.selectbox("Tipo de Simulação", ["Aluguel", "Compra"])
        st.session_state['valor_emprestado'] = st.number_input("Valor Obra", value=7600000.0, step=100000.0)

        if st.session_state['tipo_operacao'] == "Aluguel":
            st.session_state['num_parcelas'] = st.selectbox("Número de Parcelas", ["24", "36", "48", "60"])
        else:
            st.session_state['num_parcelas'] = st.selectbox("Número de Parcelas", ["28", "40", "52", "64"])

        st.session_state['tir_desejada'] = st.number_input("TIR Desejada (%)", value=2.40, step=0.1)
        st.session_state['ipca'] = st.number_input("IPCA (%)", value=4.0, step=0.1)
        st.session_state['pis'] = 0.65
        st.session_state['aliquota_cofins'] = 3

        # st.write("### Alíquotas:")
        # st.session_state['pis'] = st.number_input("PIS (%)", value=0.65, step=0.01)
        # st.session_state['cofins'] = st.number_input("Cofins (%)", value=3.0, step=0.1)
        # st.session_state['irpj'] = st.number_input("IRPJ (%)", value=15.0, step=0.1)
        # st.session_state['cssl'] = st.number_input("CSSL (%)", value=9.0, step=0.1)
        # st.session_state['irpj_adc'] = st.number_input("IRPJ Adicional (%)", value=10.0, step=0.1)
        
        # st.write("### Alíquota Base - Cálculo IRPJ e CSSL:")
        # st.session_state['base_aluguel_irpj'] = st.number_input("Base Aluguel - IRPJ (%)", value=32.0, step=0.1)
        # st.session_state['base_aluguel_cssl'] = st.number_input("Base Aluguel - CSSL (%)", value=32.0, step=0.1)
        # st.session_state['base_venda_irpj'] = st.number_input("Base Venda - IRPJ (%)", value=8.0, step=0.1)
        # st.session_state['base_venda_cssl'] = st.number_input("Base Venda - CSSL (%)", value=12.0, step=0.1)

        if st.button('Continuar'):
            st.session_state['premissas'] = True
            st.session_state['simulacao'] = True
            st.rerun()

    if 'simulacao' in st.session_state and st.session_state['simulacao']:

        tab1, tab2, tab3 = st.tabs(["Simulação", "Visão Cliente", "Visão K2"])
        # Caixa de seleção para ano
        with tab1:

            st.title("Simulação de Empréstimo")

            valor_emprestado = st.session_state['valor_emprestado']
            num_parcelas = int(st.session_state['num_parcelas'])
            tir_desejada = st.session_state['tir_desejada'] / 100
            inflacao_anual = st.session_state['ipca'] / 100
            tipo_operacao = st.session_state['tipo_operacao']
            aliquota_pis = st.session_state['pis'] / 100
            aliquota_cofins = st.session_state['aliquota_cofins'] / 100

            # aliquota_irpj = st.session_state['irpj'] / 100
            # aliquota_cssl = st.session_state['cssl'] / 100
            # aliquota_irpj_adicional = st.session_state['irpj_adc'] / 100

            # base_aluguel_irpj = st.session_state['base_aluguel_irpj']
            # base_aluguel_cssl = st.session_state['base_aluguel_cssl']
            # base_venda_irpj = st.session_state['base_venda_irpj']
            # base_venda_cssl = st.session_state['base_venda_cssl']

            st.subheader(f"Tipo de Operação: **{tipo_operacao}**")
            
            pmt_otimizada, fluxo_bruta, fluxo_liquida, df_fluxos = simular_emprestimo(
                valor_emprestado, num_parcelas, tir_desejada, inflacao_anual,
                aliquota_pis, aliquota_cofins,
                tipo_operacao=tipo_operacao,
                aliquota_irpj=0.15, aliquota_cssl=0.09,
                limite_isencao_irpj=60000, aliquota_adicional_irpj=0.10
            )

            # Calcula a soma de cada imposto
            total_pis = df_fluxos["PIS"].sum()
            total_cofins = df_fluxos["COFINS"].sum()
            total_cssl = df_fluxos["CSSL"].sum()
            total_irpj = df_fluxos["IRPJ"].sum()

            # Cria um DataFrame com os totais usando os cabeçalhos solicitados
            df_totais = pd.DataFrame({
                "Total Pis": [total_pis],
                "Total Cofins": [total_cofins],
                "Total CSSL": [total_cssl],
                "Total IRPJ": [total_irpj]
            })

            # Filtra as linhas referentes às parcelas (excluindo a linha 0 e a linha extra final)
            df_parcelas = df_fluxos[df_fluxos["Mês"].between(1, df_fluxos["Mês"].max())]

            # Calcula os valores do resumo:
            parcelas = len(df_fluxos[df_fluxos["Fluxo de Caixa Bruta"]!=0])
            total_parcelamento = df_parcelas["Fluxo de Caixa Bruta"].sum()
            total_impostos = (df_parcelas["PIS"] + 
                            df_parcelas["COFINS"] + 
                            df_parcelas["CSSL"] + 
                            df_parcelas["IRPJ"]).sum()

            receita_liquida_total = df_parcelas["Fluxo de Caixa Líquida"].sum()

            # Cria o DataFrame resumo com a primeira linha
            df_resumo = pd.DataFrame({
                "Parcelas": [parcelas-1],
                "Total Parcelamento": [total_parcelamento],
                "Total Impostos": [total_impostos],
                "Receita Líquida Total": [receita_liquida_total]
            })

            # Calcula a TIR bruta e a TIR líquida utilizando a série completa de fluxos
            tir_bruta = npf.irr(df_fluxos["Fluxo de Caixa Bruta"].values)*100
            tir_liquida = npf.irr(df_fluxos["Fluxo de Caixa Líquida"].values)*100

            # Aplicando a formatação correta antes de inserir no DataFrame
            tir_bruta = f"{tir_bruta:.2f}".replace(".", ",") + "%"
            tir_liquida = f"{tir_liquida:.2f}".replace(".", ",") + "%"

            # Cria uma segunda linha com os rótulos e os valores de TIR
            nova_linha = {
                "Parcelas": "TIR Bruta",
                "Total Parcelamento": tir_bruta,
                "Total Impostos": "TIR Líquida",
                "Receita Líquida Total": tir_liquida
            }

            # Acrescenta a nova linha usando pd.concat (o método .append está depreciado)
            df_resumo = pd.concat([df_resumo, pd.DataFrame([nova_linha])], ignore_index=True)

            # Criando colunas para colocar as caixas de seleção lado a lado
            col1, col2 = st.columns(2)

            with col1:
                # Aplicando a formatação correta
                for col in df_resumo.columns[1:]:  # Ignora a primeira coluna ('Parcelas')
                    df_resumo[col] = df_resumo[col].apply(formatar_brasileiro)

                # CSS customizado para estilização
                custom_css = """
                <style>
                    .custom-table {
                        border-collapse: collapse;
                        width: 100%;
                        font-family: 'Roboto', sans-serif;
                        font-size: 16px;
                        margin-top: 20px;
                        margin-bottom: 20px;
                        color: #ffffff;
                        position: relative;
                        z-index: 0;
                    }

                    /* Cabeçalho azul escuro com texto branco e negrito */
                    .custom-table thead tr {
                        background-color: #1B365D;
                    }

                    .custom-table th {
                        border: 1px solid #444444;
                        text-align: center;
                        padding: 10px;
                        white-space: nowrap;
                        font-size: 17px;
                        font-weight: bold;
                        color: #ffffff;
                    }

                    /* Linhas alternadas entre cinza escuro e preto */
                    .custom-table tbody tr:nth-child(even) {
                        background-color: #2B2B2B;
                    }

                    .custom-table tbody tr:nth-child(odd) {
                        background-color: #242424;
                    }

                    .custom-table td {
                        border: 1px solid #444444;
                        text-align: center;
                        padding: 10px;
                        white-space: nowrap;
                        font-size: 16px;
                        color: #ffffff;
                    }
                </style>
                """

                # Convertendo o DataFrame para HTML
                tabela_html = df_resumo.to_html(classes="custom-table", index=False, escape=False)

                # Exibindo no Streamlit
                st.markdown(custom_css, unsafe_allow_html=True)
                st.markdown(tabela_html, unsafe_allow_html=True)

            with col2:
                # Aplicando a formatação correta em todas as colunas
                for col in df_totais.columns:
                    df_totais[col] = df_totais[col].apply(formatar_brasileiro)

                # CSS customizado para estilização
                custom_css = """
                <style>
                    .custom-table {
                        border-collapse: collapse;
                        width: 100%;
                        font-family: 'Roboto', sans-serif;
                        font-size: 16px;
                        margin-top: 20px;
                        margin-bottom: 20px;
                        color: #ffffff;
                        position: relative;
                        z-index: 0;
                    }

                    /* Cabeçalho azul escuro com texto branco e negrito */
                    .custom-table thead tr {
                        background-color: #1B365D;
                    }

                    .custom-table th {
                        border: 1px solid #444444;
                        text-align: center;
                        padding: 10px;
                        white-space: nowrap;
                        font-size: 17px;
                        font-weight: bold;
                        color: #ffffff;
                    }

                    /* Linhas alternadas entre cinza escuro e preto */
                    .custom-table tbody tr:nth-child(even) {
                        background-color: #2B2B2B;
                    }

                    .custom-table tbody tr:nth-child(odd) {
                        background-color: #242424;
                    }

                    .custom-table td {
                        border: 1px solid #444444;
                        text-align: center;
                        padding: 10px;
                        white-space: nowrap;
                        font-size: 16px;
                        color: #ffffff;
                    }
                </style>
                """

                # Convertendo o DataFrame para HTML
                tabela_html = df_totais.to_html(classes="custom-table", index=False, escape=False)

                # Exibindo no Streamlit
                st.markdown(custom_css, unsafe_allow_html=True)
                st.markdown(tabela_html, unsafe_allow_html=True)

            # Aplicando a formatação correta em todas as colunas, exceto "Mês"
            for col in df_fluxos.columns[1:]:
                df_fluxos[col] = df_fluxos[col].apply(formatar_brasileiro)

            # CSS customizado para estilização
            custom_css = """
            <style>
                .custom-table {
                    border-collapse: collapse;
                    width: 100%;
                    font-family: 'Roboto', sans-serif;
                    font-size: 14px;
                    margin-top: 20px;
                    margin-bottom: 20px;
                    color: #ffffff;
                    position: relative;
                    z-index: 0;
                }

                /* Cabeçalho azul escuro com texto branco e negrito */
                .custom-table thead tr {
                    background-color: #1B365D;
                }

                .custom-table th {
                    border: 1px solid #444444;
                    text-align: center;
                    padding: 8px;
                    white-space: nowrap;
                    font-size: 15px;
                    font-weight: bold;
                    color: #ffffff;
                }

                /* Linhas alternadas entre cinza escuro e preto */
                .custom-table tbody tr:nth-child(even) {
                    background-color: #2B2B2B;
                }

                .custom-table tbody tr:nth-child(odd) {
                    background-color: #242424;
                }

                .custom-table td {
                    border: 1px solid #444444;
                    text-align: center;
                    padding: 8px;
                    white-space: nowrap;
                    font-size: 14px;
                    color: #ffffff;
                }
            </style>
            """

            # Convertendo o DataFrame para HTML
            tabela_html = df_fluxos.to_html(classes="custom-table", index=False, escape=False)

            # Exibindo no Streamlit
            st.markdown(custom_css, unsafe_allow_html=True)
            st.markdown(tabela_html, unsafe_allow_html=True)

        # Caixa de seleção para ano
        with tab2:
            st.title("Visão Cliente - Investimento")
            # --- Parâmetros ---
            st.session_state['recuperacao_irpj'] = 0.34         # Taxa de recuperação de IR (34%)
            cdi = 0.01134762                # Taxa CDI mensal (ex: 1%)
            valor_obra = st.session_state['valor_emprestado']   # Valor total da obra


            # Filtra os meses com fluxo diferente de zero (os meses com pagamentos)
            df_parcelas_recuperacao = df_fluxos[df_fluxos["Fluxo de Caixa Bruta"] != 0].copy()
            # Convertendo as colunas para float, substituindo a vírgula por ponto
            cols_to_convert = [
                "Fluxo de Caixa Bruta", "Fluxo de Caixa Líquida", "PIS", "COFINS",
                "Base Tributável CSSL", "CSSL", "Base Tributável IRPJ", "Base Adicional IRPJ",
                "IRPJ", "IRPJ Adicional"
            ]
            for col in cols_to_convert:
                df_parcelas_recuperacao[col] = df_parcelas_recuperacao[col].str.replace('.', '').str.replace(',', '.').astype(float)

            # Ordena pelo mês e reseta o índice
            df_parcelas_recuperacao.sort_values("Mês", inplace=True)
            df_parcelas_recuperacao.reset_index(drop=True, inplace=True)

            # Inicializa as colunas que serão usadas na simulação
            df_parcelas_recuperacao['Inicio  Mês'] = 0.0
            df_parcelas_recuperacao['Saldo'] = 0.0
            df_parcelas_recuperacao['Rec Liquida'] = 0.0

            # Garante que o fluxo do mês 0 seja zero (mesmo que já esteja)
            df_parcelas_recuperacao.loc[df_parcelas_recuperacao["Mês"] == 0, "Fluxo de Caixa Bruta"] = 0

            # Cria a coluna "Parcela" invertendo o sinal do "Fluxo de Caixa Bruta"
            # Assim, as parcelas (de meses 1 em diante) ficarão negativas, indicando saídas.
            df_parcelas_recuperacao['Parcela'] = -df_parcelas_recuperacao["Fluxo de Caixa Bruta"]

            # Calcula a "Recuperação IR" para cada mês:
            # Para operação "aluguel": Recuperação IR = -Parcela * recuperacao_irpj
            # Para operação "compra": nos últimos 4 meses, não há recuperação, logo será 0.
            df_parcelas_recuperacao['Recuperação IR'] = -df_parcelas_recuperacao['Parcela'] * st.session_state['recuperacao_irpj']

            if tipo_operacao == "compra":
                max_mes = df_parcelas_recuperacao["Mês"].max()
                # Define os últimos 4 meses: para meses com Mês >= (max_mes - 3) a Recuperação IR é 0.
                df_parcelas_recuperacao.loc[df_parcelas_recuperacao["Mês"] >= max_mes - 3, "Recuperação IR"] = 0

            # --- Cálculo do Valor Inicial (valor_emprestado) ---
            # Para cada mês i (>=1), o efeito líquido do pagamento é:
            #   - Em "aluguel": Efeito = Parcela + Recuperação IR = Parcela * (1 - recuperacao_irpj)
            #   - Em "compra": se o mês estiver entre os últimos 4, a Recuperação IR não ocorre, logo o efeito = Parcela
            #                caso contrário, o efeito é o mesmo de "aluguel".
            parcelas_abs = -df_parcelas_recuperacao.loc[df_parcelas_recuperacao["Mês"] != 0, "Parcela"]

            max_mes = df_parcelas_recuperacao["Mês"].max()
            soma_ajustada = 0.0
            for i, valor in zip(df_parcelas_recuperacao.loc[df_parcelas_recuperacao["Mês"] != 0, "Mês"], parcelas_abs):
                if tipo_operacao == "compra" and i >= max_mes - 3:
                    fator = 1.0
                else:
                    fator = (1 - st.session_state['recuperacao_irpj'])
                soma_ajustada += fator * (valor / ((1 + cdi) ** i))

            valor_emprestado = soma_ajustada

            # Atribui o valor inicial (valor_emprestado) ao mês 0 nas colunas "Inicio  Mês" e "Rec Liquida"
            df_parcelas_recuperacao.loc[df_parcelas_recuperacao["Mês"] == 0, "Inicio  Mês"] = valor_emprestado
            df_parcelas_recuperacao.loc[df_parcelas_recuperacao["Mês"] == 0, "Rec Liquida"] = valor_emprestado
            df_parcelas_recuperacao.loc[df_parcelas_recuperacao["Mês"] == 0, "Saldo"] = valor_emprestado

            # --- Simulação da Evolução Mensal com CDI ---
            # Para cada mês i (>=1):
            #   - "Inicio  Mês" = Saldo do mês anterior * (1 + CDI)
            #   - "Saldo" = "Inicio  Mês" + Parcela + Recuperação IR
            #   - "Rec Liquida" = Parcela + Recuperação IR (neto do pagamento)
            for idx in df_parcelas_recuperacao.index:
                mes = df_parcelas_recuperacao.at[idx, "Mês"]
                if mes == 0:
                    continue  # Já definido
                prev_idx = idx - 1
                inicio_mes = df_parcelas_recuperacao.at[prev_idx, "Saldo"] * (1 + cdi)
                df_parcelas_recuperacao.at[idx, "Inicio  Mês"] = inicio_mes
                parcela = df_parcelas_recuperacao.at[idx, "Parcela"]
                rec_ir = df_parcelas_recuperacao.at[idx, "Recuperação IR"]
                saldo = inicio_mes + parcela + rec_ir
                df_parcelas_recuperacao.at[idx, "Saldo"] = saldo
                df_parcelas_recuperacao.at[idx, "Rec Liquida"] = parcela + rec_ir

            # --- Reorganiza as colunas na ordem desejada ---
            df_parcelas_recuperacao = df_parcelas_recuperacao[["Mês", "Inicio  Mês", "Parcela", "Recuperação IR", "Saldo", "Rec Liquida"]]

            df_parcelas_recuperacao.loc[df_parcelas_recuperacao["Mês"] == 0, "Rec Liquida"] = valor_obra

            # --- Cálculo do IRR ---
            irr_rec_liquida = npf.irr(df_parcelas_recuperacao["Rec Liquida"]) * 100
            irr_rec_liquida = f"{irr_rec_liquida:.3f}".replace(".", ",") + "%"
            recuperado = df_parcelas_recuperacao["Recuperação IR"].sum()
            recuperado = f"{recuperado:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            # Estilos customizados para os cards
            card_style = """
                <style>
                    .card {
                        background-color: #1B365D;
                        padding: 20px;
                        border-radius: 10px;
                        box-shadow: 0px 4px 10px rgba(0, 0, 0, 0.3);
                        text-align: center;
                        color: white;
                        font-size: 20px;
                        font-weight: bold;
                        margin-bottom: 10px;
                    }
                    .highlight {
                        font-size: 30px;
                        font-weight: bold;
                        color: #FFC300;
                    }
                </style>
            """

            # Aplica o estilo
            st.markdown(card_style, unsafe_allow_html=True)

            # Criando colunas para exibir os cards lado a lado
            col1, col2 = st.columns(2)

            with col1:
                st.markdown(f"""
                    <div class="card">
                        TIR com Recuperação IR<br>
                        <span class="highlight">{irr_rec_liquida:}</span>
                    </div>
                """, unsafe_allow_html=True)

            with col2:
                st.markdown(f"""
                    <div class="card">
                        Recuperação IR<br>
                        <span class="highlight">{recuperado}</span>
                    </div>
                """, unsafe_allow_html=True)

            # Aplicando a formatação correta em todas as colunas, exceto "Mês"
            for col in df_parcelas_recuperacao.columns[1:]:
                df_parcelas_recuperacao[col] = df_parcelas_recuperacao[col].apply(formatar_brasileiro)

            # CSS customizado para estilização
            custom_css = """
            <style>
                .custom-table {
                    border-collapse: collapse;
                    width: 100%;
                    font-family: 'Roboto', sans-serif;
                    font-size: 14px;
                    margin-top: 20px;
                    margin-bottom: 20px;
                    color: #ffffff;
                    position: relative;
                    z-index: 0;
                }

                /* Cabeçalho azul escuro com texto branco e negrito */
                .custom-table thead tr {
                    background-color: #1B365D;
                }

                .custom-table th {
                    border: 1px solid #444444;
                    text-align: center;
                    padding: 8px;
                    white-space: nowrap;
                    font-size: 15px;
                    font-weight: bold;
                    color: #ffffff;
                }

                /* Linhas alternadas entre cinza escuro e preto */
                .custom-table tbody tr:nth-child(even) {
                    background-color: #2B2B2B;
                }

                .custom-table tbody tr:nth-child(odd) {
                    background-color: #242424;
                }

                .custom-table td {
                    border: 1px solid #444444;
                    text-align: center;
                    padding: 8px;
                    white-space: nowrap;
                    font-size: 14px;
                    color: #ffffff;
                }
            </style>
            """

            # Convertendo o DataFrame para HTML
            tabela_html = df_parcelas_recuperacao.to_html(classes="custom-table", index=False, escape=False)

            # Exibindo no Streamlit com CSS aplicado
            st.markdown(custom_css, unsafe_allow_html=True)
            st.markdown(tabela_html, unsafe_allow_html=True)    

        # Caixa de seleção para ano
        with tab3:
            st.write("### Detalhes dos Fluxos")


        if st.button('Voltar'):
            del st.session_state['simulacao']
            del st.session_state['premissas']
            st.rerun()