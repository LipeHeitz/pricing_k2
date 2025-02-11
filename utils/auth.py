import streamlit as st
import time

# Dicionário de usuários e senhas
users = {
    "OV": "principal",
    "FH": "principal",
    "TEMI": "secundario",
    "TEMI1": "consulta",
}

def authenticate(username, password):
    if username in users and users[username] == password:
        return True
    else:
        return False

def login():
    st.title("Login")

    # Verifica se a senha foi submetida
    if 'password_submitted' not in st.session_state:
        st.session_state['password_submitted'] = False

    # Campo de nome de usuário
    username = st.text_input("Usuário")

    # Campo de senha
    password = st.text_input("Senha", type="password", on_change=lambda: st.session_state.update(password_submitted=True))

    # Verifica se a senha foi submetida e processa o login
    if st.session_state['password_submitted']:
        if authenticate(username, password):
            st.session_state['authenticated'] = True
            st.session_state['username'] = username  # Armazena o nome de usuário na sessão
            st.session_state['senha'] = password  # Armazena a senha na sessão
            st.rerun()  # Força a recarga da página
        else:
            st.session_state['password_submitted'] = False
            erro = st.error("Usuário ou senha incorretos. Tente novamente.")
            time.sleep(2)
            erro.empty()

    # Botão de login para fallback, caso o usuário prefira clicar
    if st.button("Entrar"):
        if authenticate(username, password):
            st.session_state['authenticated'] = True
            st.session_state['username'] = username  # Armazena o nome de usuário na sessão
            st.session_state['senha'] = password
            st.rerun()  # Força a recarga da página
        else:
            st.error("Usuário ou senha incorretos. Tente novamente.")

def logout():
    st.session_state['authenticated'] = False
    st.session_state['password_submitted'] = False 
    if 'username' in st.session_state:
        del st.session_state['username']
    if 'senha' in st.session_state:
        del st.session_state['senha']