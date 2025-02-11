import streamlit as st
from streamlit_option_menu import option_menu
from Paginas import premissas, cockpit, proposta
from utils.auth import login, logout

# Função para verificar autenticação
def check_auth():
    if 'authenticated' not in st.session_state:
        st.session_state['authenticated'] = False

check_auth()

if st.session_state['authenticated']:
    st.set_page_config(layout="wide", page_title="K2", initial_sidebar_state="expanded", page_icon="📊")
    
    # Exibe o nome do usuário autenticado na sidebar
    with st.sidebar:
        st.title(f"Bem-vindo, {st.session_state['username']}")

        # Define o menu de navegação com base no usuário
        if st.session_state['senha'] == 'principal' or st.session_state['senha'] == 'secundario':
            menu_options = ['Premissas', 'Cockpit', 'Proposta']
            menu_icons = ['grid']
        
        elif st.session_state['senha'] == 'consulta':
            menu_options = ['Premissas', 'Cockpit', 'Proposta']
            menu_icons = ['grid']
                    
        else:
            menu_options = ['Help']
            menu_icons = ['question-circle']

        # Menu de navegação com ícones na sidebar
        menu = option_menu(
            None, menu_options, 
            icons=menu_icons, 
            menu_icon="cast", default_index=0,
            styles={
                "container": {"padding": "5px", "background-color": "#2E2E2E", "border-radius": "10px"},
                "icon": {"color": "orange", "font-size": "20px"},
                "nav-link": {"font-size": "16px", "color": "white", "text-align": "left", "margin":"0px", "--hover-color": "#555555"},
                "nav-link-selected": {"background-color": "#1a1a1a", "color": "white"},
            }
        )
        
        st.button("Logout", on_click=logout)

    # Navegação nas páginas
    if menu == 'Premissas':
        premissas.app()
    elif menu == 'Cockpit':
        cockpit.app()
    elif menu == 'Proposta':
        proposta.app()

else:
    login()