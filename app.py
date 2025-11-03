me  cria tambem uma area onde constará uma ficha com 6 jogos com under 3,5 golos e over 0,5 golos:

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText as MimeText
from email.mime.multipart import MIMEMultipart as MimeMultipart
import io
from fpdf import FPDF
# --- 1. CONFIGURAÇÃO INICIAL E VARIÁVEIS DE AMBIENTE ---
load_dotenv()
st.set_page_config(
    page_title="⚽ Analisador Automático de Apostas",
    layout="wide",
    page_icon="⚽"
)
# Chaves API e Email
# Use "DEFAULT_KEY" se a chave não estiver no .env para evitar falha
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "DEFAULT_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "sua_chave_the_odds_api")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
HEADERS_FOOTBALL = {
    "X-Auth-Token": FOOTBALL_DATA_API_KEY,
    "Accept": "application/json"
}
HEADERS_ODDS = {
    "Authorization": f"apikey {ODDS_API_KEY}"
}
BASE_URL_FOOTBALL = "https://api.football-data.org/v4"
BASE_URL_ODDS = "https://api.the-odds-api.com/v4"
# --- 2. FUNÇÕES DE UTILIDADE E CÁLCULO (Globais) ---
def calculate_implied_probability(odd):
    return round(100 / odd, 2) if odd and odd > 0 else None
def calculate_value_bet(real_prob, odd):
    if not odd or odd <= 0 or not real_prob:
        return None
    return round((odd * (real_prob / 100)) - 1, 3)
# Funções auxiliares de gols (para uso em APIs e H2H)
def get_total_goals(match):
    return (match['score']['fullTime'].get('home', 0) or 0) + (match['score']['fullTime'].get('away', 0) or 0)
def get_home_goals(match):
    return match['score']['fullTime'].get('home', 0) or 0
def get_away_goals(match):
    return match['score']['fullTime'].get('away', 0) or 0
def get_first_half_goals(match):
    return (match['score']['halfTime'].get('home', 0) or 0) + (match['score']['halfTime'].get('away', 0) or 0)
def get_second_half_goals(match):
    return get_total_goals(match) - get_first_half_goals(match)
# --- 3. FUNÇÕES DE API (Tudo cacheado para evitar limites) ---
@st.cache_data(ttl=3600)
def fetch_football_data(endpoint):
    """Busca dados da Football-Data API com verificação de limite."""
    if FOOTBALL_DATA_API_KEY == "DEFAULT_KEY":
        st.error("❌ A chave FOOTBALL_DATA_API_KEY não está configurada no seu ambiente.")
        return None
       
    try:
        url = f"{BASE_URL_FOOTBALL}/{endpoint}"
        response = requests.get(url, headers=HEADERS_FOOTBALL, timeout=15)
       
        if response.status_code == 429:
            st.error("❌ Limite de requisições da API Football-Data atingido. Tente novamente mais tarde.")
            return None
       
        return response.json() if response.status_code == 200 else None
    except Exception:
        return None
@st.cache_data(ttl=3600)
def get_competitions():
    """Busca a lista de competições e IDs (Cache 1 hora)."""
    data = fetch_football_data("competitions")
    if data and "competitions" in data:
        comp_dict = {}
        top_competitions_names = [
            "Premier League", "Primera Division", "Serie A", "Bundesliga",
            "Ligue 1", "Primeira Liga", "Eredivisie", "Jupiler Pro League",
            "Scottish Premiership",
            "UEFA Champions League", "UEFA Europa League", "UEFA Conference League"
        ]
        for comp in data["competitions"]:
            if comp["name"] in top_competitions_names and comp.get("currentSeason"):
                comp_dict[comp["name"]] = comp["id"]
        return comp_dict
    return {}
@st.cache_data(ttl=600) # Cache de 10 minutos para partidas
def get_matches(competition_id):
    """Busca as próximas partidas para uma competição."""
    today = datetime.now().strftime("%Y-%m-%d")
    next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
   
    data = fetch_football_data(f"competitions/{competition_id}/matches?dateFrom={today}&dateTo={next_week}")
    return data.get("matches", []) if data else []
@st.cache_data(ttl=3600) # CACHE CRUCIAL: Perfis de time (evita 4 chamadas/análise)
def fetch_team_profile_cached(team_id, comp_id):
    """Busca o perfil de um time (requer 2 chamadas API) de forma cacheada."""
   
    profile = {'ataque': 5, 'defesa': 5, 'estilo': 'equilibrado', 'over25': 50, 'btts': 50, 'over15': 70, 'under35': 70, 'under25': 50, 'second_half_more': 50}
   
    try:
        # 1. Standings para médias da temporada (1ª chamada API)
        standings_data = fetch_football_data(f"competitions/{comp_id}/standings")
       
        if standings_data and 'standings' in standings_data:
            for group in standings_data['standings']:
                for team_entry in group['table']:
                    if team_entry['team']['id'] == team_id:
                        played = team_entry['playedGames']
                        gf = team_entry['goalsFor']
                        ga = team_entry['goalsAgainst']
                        if played > 0:
                            avg_scored = gf / played
                            avg_conceded = ga / played
                            profile['ataque'] = min(10, max(1, round((avg_scored / 1.4) * 7 + 1)))
                            profile['defesa'] = min(10, max(1, round((1.4 / max(avg_conceded, 0.1)) * 7 + 1)))
                        break
       
        # 2. Matches recentes para estatísticas de mercado (2ª chamada API)
        matches_data = fetch_football_data(f"teams/{team_id}/matches?status=FINISHED&limit=10")
       
        if matches_data and 'matches' in matches_data:
            recent_matches = matches_data['matches'][:10]
            if recent_matches:
                total_over25 = sum(1 for m in recent_matches if get_total_goals(m) > 2.5)
                total_btts = sum(1 for m in recent_matches if get_home_goals(m) > 0 and get_away_goals(m) > 0)
                total_over15 = sum(1 for m in recent_matches if get_total_goals(m) > 1.5)
                total_under35 = sum(1 for m in recent_matches if get_total_goals(m) < 3.5)
                total_under25 = sum(1 for m in recent_matches if get_total_goals(m) < 2.5)
                total_second_half_more = sum(1 for m in recent_matches if get_second_half_goals(m) > get_first_half_goals(m))
               
                profile['over25'] = round((total_over25 / len(recent_matches)) * 100)
                profile['btts'] = round((total_btts / len(recent_matches)) * 100)
                profile['over15'] = round((total_over15 / len(recent_matches)) * 100)
                profile['under35'] = round((total_under35 / len(recent_matches)) * 100)
                profile['under25'] = round((total_under25 / len(recent_matches)) * 100)
                profile['second_half_more'] = round((total_second_half_more / len(recent_matches)) * 100)
       
        # Determinação do estilo
        attack, defense = profile['ataque'], profile['defesa']
        if attack >= 7 and defense <= 6:
            profile['estilo'] = 'ofensivo'
        elif defense >= 7 and attack <= 6:
            profile['estilo'] = 'defensivo'
        else:
            profile['estilo'] = 'equilibrado'
           
        return profile
    except Exception:
        return profile

# --- NOVA FUNÇÃO: Buscar jogos com alta probabilidade de Under 3.5 e Over 0.5 ---
@st.cache_data(ttl=1800)  # Cache de 30 minutos
def get_under_35_over_05_matches():
    """Busca jogos com alta probabilidade de Under 3.5 e Over 0.5 gols"""
    try:
        competitions = get_competitions()
        matches_under_35 = []
        
        for comp_name, comp_id in competitions.items():
            matches = get_matches(comp_id)
            
            for match in matches:
                if match["status"] in ["SCHEDULED", "TIMED"]:
                    try:
                        home_id = match["homeTeam"]["id"]
                        away_id = match["awayTeam"]["id"]
                        
                        # Obter perfis dos times
                        home_profile = fetch_team_profile_cached(home_id, comp_id)
                        away_profile = fetch_team_profile_cached(away_id, comp_id)
                        
                        # Calcular probabilidade combinada
                        prob_under_35 = (home_profile['under35'] + away_profile['under35']) / 2
                        prob_over_05 = 100 - ((home_profile['under25'] + away_profile['under25']) / 4)  # Estimativa para Over 0.5
                        
                        # Ajustar baseado no estilo dos times
                        if home_profile['estilo'] == 'defensivo' and away_profile['estilo'] == 'defensivo':
                            prob_under_35 += 15
                            prob_over_05 -= 5
                        elif home_profile['estilo'] == 'defensivo' or away_profile['estilo'] == 'defensivo':
                            prob_under_35 += 8
                        
                        # Limitar probabilidades
                        prob_under_35 = min(95, max(50, prob_under_35))
                        prob_over_05 = min(95, max(60, prob_over_05))
                        
                        # Critério de seleção: Under 3.5 > 70% e Over 0.5 > 75%
                        if prob_under_35 >= 70 and prob_over_05 >= 75:
                            match_date = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
                            
                            matches_under_35.append({
                                'competition': comp_name,
                                'home_team': match["homeTeam"]["name"],
                                'away_team': match["awayTeam"]["name"],
                                'date': match_date,
                                'prob_under_35': round(prob_under_35, 1),
                                'prob_over_05': round(prob_over_05, 1),
                                'home_style': home_profile['estilo'],
                                'away_style': away_profile['estilo'],
                                'home_attack': home_profile['ataque'],
                                'home_defense': home_profile['defesa'],
                                'away_attack': away_profile['ataque'],
                                'away_defense': away_profile['defesa']
                            })
                            
                            # Limitar a 12 jogos no máximo
                            if len(matches_under_35) >= 12:
                                break
                                
                    except Exception as e:
                        continue
                        
        # Ordenar por probabilidade de Under 3.5 (maior primeiro)
        matches_under_35.sort(key=lambda x: x['prob_under_35'], reverse=True)
        
        # Retornar apenas os 6 melhores
        return matches_under_35[:6]
        
    except Exception as e:
        st.error(f"Erro ao buscar jogos Under 3.5/Over 0.5: {e}")
        return []
# --- 4. CLASSE MOTOR DE ANÁLISE (ATUALIZADA) ---
class AnalisadorAutomatico:
    def __init__(self):
        # GARANTIA DE ESTADO: Inicializa session_state se necessário
        if 'watchlist' not in st.session_state:
            st.session_state.watchlist = []
        if 'historico_analises' not in st.session_state:
            st.session_state.historico_analises = []
           
        self.watchlist = st.session_state.watchlist
        self.historico_analises = st.session_state.historico_analises
   
    # --- Métodos de Estado ---
    def save_historico(self, analise, home_team, away_team):
        self.historico_analises.append({
            'home': home_team,
            'away': away_team,
            'prob_btts': analise['prob_btts'],
            'prob_over25': analise['prob_over25'],
            'data': datetime.now().strftime('%Y-%m-%d %H:%M')
        })
        st.session_state.historico_analises = self.historico_analises
   
    # --- Métodos de API (H2H Corrigido com _self) ---
    @st.cache_data(ttl=3600)
    def fetch_h2h(_self, home_id, away_id, limit=5): # <-- CORREÇÃO: Usando _self
        try:
            # Reusa funções globais de gols
            home_matches = fetch_football_data(f"teams/{home_id}/matches?status=FINISHED&limit=20")
            h2h = []
            if home_matches and 'matches' in home_matches:
                for m in home_matches['matches']:
                    if m.get('awayTeam', {}).get('id') == away_id or m.get('homeTeam', {}).get('id') == away_id:
                        h2h.append(m)
                        if len(h2h) >= limit:
                            break
            h2h_stats = {
                'btts_h2h': sum(1 for m in h2h if get_home_goals(m) > 0 and get_away_goals(m) > 0) / max(len(h2h), 1) * 100,
                'over25_h2h': sum(1 for m in h2h if get_total_goals(m) > 2.5) / max(len(h2h), 1) * 100
            }
            return h2h_stats
        except Exception:
            return {'btts_h2h': 50, 'over25_h2h': 50}
   
    def fetch_live_odds(self, home_team, away_team):
        try:
            if ODDS_API_KEY == "sua_chave_the_odds_api":
                return []
           
            regions = 'eu' # Europa (pode ser ajustado)
            # Nota: The Odds API usa chaves 'sport' como 'soccer_epl' (Premier League) ou apenas 'soccer'
            url = f"{BASE_URL_ODDS}/sports/soccer/odds/?apiKey={ODDS_API_KEY}&regions={regions}&markets=h2h,totals"
            response = requests.get(url, headers=HEADERS_ODDS, timeout=10)
           
            if response.status_code == 200:
                odds_data = response.json()
                for event in odds_data:
                    # Busca por correspondência parcial de nome
                    if home_team.lower() in event['home_team'].lower() and away_team.lower() in event['away_team'].lower():
                        return event.get('bookmakers', [])
            return []
        except Exception:
            return []
   
    # --- Lógica de Análise Principal ---
    def analisar_partida_automatica(self, home_team, away_team, competition, home_id, away_id, comp_id, selected_markets):
       
        # CHAMA FUNÇÕES DE PERFIL E H2H CACHEADAS
        home_profile = fetch_team_profile_cached(home_id, comp_id)
        away_profile = fetch_team_profile_cached(away_id, comp_id)
        # O self aqui é apenas a chamada, o método interno usa _self
        h2h_adjust = self.fetch_h2h(home_id, away_id)
       
        # Cálculo de probabilidades baseadas nos perfis (mantido)
        prob_btts_base = (home_profile['btts'] + away_profile['btts']) / 2
        prob_over25_base = (home_profile['over25'] + away_profile['over25']) / 2
        prob_over15_base = (home_profile['over15'] + away_profile['over15']) / 2
        prob_under35_base = (home_profile['under35'] + away_profile['under35']) / 2
        prob_under25_base = (home_profile['under25'] + away_profile['under25']) / 2
        prob_second_half_more_base = (home_profile['second_half_more'] + away_profile['second_half_more']) / 2
       
        ajustes = self.calcular_ajustes_estilo(home_profile, away_profile)
        ajustes_competicao = self.calcular_ajustes_competicao(competition)
       
        # Aplicação de ajustes e limites (mantido)
        prob_btts_final = min(85, max(15, prob_btts_base + ajustes['btts'] + ajustes_competicao['btts'] + (h2h_adjust['btts_h2h'] - 50)/10))
        prob_over25_final = min(80, max(20, prob_over25_base + ajustes['over25'] + ajustes_competicao['over25'] + (h2h_adjust['over25_h2h'] - 50)/10))
        prob_over15_final = min(95, max(40, prob_over15_base + ajustes['over15'] + ajustes_competicao['over15']))
        prob_under35_final = min(90, max(30, prob_under35_base + ajustes['under35'] + ajustes_competicao['under35']))
        prob_under25_final = min(85, max(25, prob_under25_base + ajustes['under25'] + ajustes_competicao['under25']))
        prob_second_half_more_final = min(80, max(20, prob_second_half_more_base + ajustes['second_half_more'] + ajustes_competicao['second_half_more']))
       
        # Cálculo das Odds Justas
        odd_justa_btts = round(100 / prob_btts_final, 2)
        odd_justa_over25 = round(100 / prob_over25_final, 2)
        odd_justa_over15 = round(100 / prob_over15_final, 2)
        odd_justa_under35 = round(100 / prob_under35_final, 2)
        odd_justa_under25 = round(100 / prob_under25_final, 2)
        odd_justa_second_half_more = round(100 / prob_second_half_more_final, 2)
       
        analise = {
            'prob_btts': round(prob_btts_final, 1),
            'prob_over25': round(prob_over25_final, 1),
            'prob_over15': round(prob_over15_final, 1),
            'prob_under35': round(prob_under35_final, 1),
            'prob_under25': round(prob_under25_final, 1),
            'prob_second_half_more': round(prob_second_half_more_final, 1),
            'odd_justa_btts': odd_justa_btts,
            'odd_justa_over25': odd_justa_over25,
            'odd_justa_over15': odd_justa_over15,
            'odd_justa_under35': odd_justa_under35,
            'odd_justa_under25': odd_justa_under25,
            'odd_justa_second_half_more': odd_justa_second_half_more,
            'h2h': h2h_adjust,
            'analise_detalhada': self.gerar_analise_detalhada(home_team, away_team, home_profile, away_profile, ajustes, h2h_adjust),
            'recomendacao': self.gerar_recomendacao(prob_btts_final, prob_over25_final, prob_over15_final, prob_under35_final, prob_under25_final, prob_second_half_more_final, selected_markets)
        }
       
        self.save_historico(analise, home_team, away_team)
        return analise
   
    # --- Métodos de Lógica e Visualização (Mantidos) ---
    def calcular_ajustes_estilo(self, home, away):
        ajustes = {'btts': 0, 'over25': 0, 'over15': 0, 'under35': 0, 'under25': 0, 'second_half_more': 0}
       
        if home['estilo'] == 'ofensivo' and away['estilo'] == 'ofensivo':
            ajustes['btts'] += 8
            ajustes['over25'] += 12
            ajustes['over15'] += 5
            ajustes['under35'] -= 10
            ajustes['under25'] -= 8
            ajustes['second_half_more'] += 5
        elif home['estilo'] == 'ofensivo' and away['estilo'] == 'defensivo':
            ajustes['btts'] += 3
            ajustes['over25'] += 2
            ajustes['over15'] += 2
            ajustes['under35'] -= 3
            ajustes['under25'] -= 2
            ajustes['second_half_more'] += 3
        elif home['estilo'] == 'defensivo' and away['estilo'] == 'ofensivo':
            ajustes['btts'] += 3
            ajustes['over25'] += 2
            ajustes['over15'] += 2
            ajustes['under35'] -= 3
            ajustes['under25'] -= 2
            ajustes['second_half_more'] += 3
        elif home['estilo'] == 'defensivo' and away['estilo'] == 'defensivo':
            ajustes['btts'] -= 10
            ajustes['over25'] -= 15
            ajustes['over15'] -= 5
            ajustes['under35'] += 12
            ajustes['under25'] += 10
            ajustes['second_half_more'] -= 5
       
        if home['ataque'] >= 8 and away['defesa'] <= 5:
            ajustes['btts'] += 5
            ajustes['over25'] += 8
            ajustes['over15'] += 4
            ajustes['under35'] -= 6
            ajustes['under25'] -= 5
            ajustes['second_half_more'] += 4
        if away['ataque'] >= 8 and home['defesa'] <= 5:
            ajustes['btts'] += 5
            ajustes['over25'] += 8
            ajustes['over15'] += 4
            ajustes['under35'] -= 6
            ajustes['under25'] -= 5
            ajustes['second_half_more'] += 4
           
        return ajustes
   
    def calcular_ajustes_competicao(self, competition):
        ajustes = {'btts': 0, 'over25': 0, 'over15': 0, 'under35': 0, 'under25': 0, 'second_half_more': 0}
       
        if 'Premier League' in competition:
            ajustes['over25'] += 5
            ajustes['over15'] += 3
            ajustes['under35'] -= 2
            ajustes['under25'] -= 1
            ajustes['second_half_more'] += 2
        elif 'Serie A' in competition:
            ajustes['btts'] -= 3
            ajustes['over25'] -= 2
            ajustes['over15'] -= 1
            ajustes['under35'] += 4
            ajustes['under25'] += 3
            ajustes['second_half_more'] -= 2
        elif 'Bundesliga' in competition:
            ajustes['btts'] += 5
            ajustes['over25'] += 8
            ajustes['over15'] += 5
            ajustes['under35'] -= 8
            ajustes['under25'] -= 7
            ajustes['second_half_more'] += 5
           
        return ajustes
   
    def gerar_analise_detalhada(self, home_team, away_team, home_profile, away_profile, ajustes, h2h):
        analise = []
       
        analise.append(f"**🏠 {home_team}**: Time **{home_profile['estilo'].upper()}** (Ataque: {home_profile['ataque']}/10, Defesa: {home_profile['defesa']}/10)")
        analise.append(f"**🚩 {away_team}**: Time **{away_profile['estilo'].upper()}** (Ataque: {away_profile['ataque']}/10, Defesa: {away_profile['defesa']}/10)")
       
        analise.append(f"**🤝 H2H Recente**: BTTS **{h2h['btts_h2h']:.0f}%** | Over 2.5 **{h2h['over25_h2h']:.0f}%**")
       
        if home_profile['estilo'] == 'ofensivo' and away_profile['estilo'] == 'ofensivo':
            analise.append("**⚔️ CONFRONTO**: Dois times ofensivos → Alta probabilidade de gols")
        elif home_profile['estilo'] == 'defensivo' and away_profile['estilo'] == 'defensivo':
            analise.append("**⚔️ CONFRONTO**: Dois times defensivos → Baixa probabilidade de gols")
        else:
            analise.append("**⚔️ CONFRONTO**: Estilos diferentes → Jogo equilibrado")
       
        if home_profile['ataque'] >= 8:
            analise.append(f"✅ {home_team} tem ataque muito forte")
        if away_profile['ataque'] >= 8:
            analise.append(f"✅ {away_team} tem ataque muito forte")
        if home_profile['defesa'] <= 5:
            analise.append(f"⚠️ {home_team} tem defesa vulnerável")
        if away_profile['defesa'] <= 5:
            analise.append(f"⚠️ {away_team} tem defesa vulnerável")
           
        return analise
   
    def gerar_recomendacao(self, prob_btts, prob_over25, prob_over15, prob_under35, prob_under25, prob_second_half_more, selected_markets):
        recomendacoes = []
       
        if 'btts' in selected_markets:
            if prob_btts >= 60:
                recomendacoes.append("🎯 **BTTS**: FORTE candidato - Probabilidade alta")
            elif prob_btts >= 50:
                recomendacoes.append("🎯 **BTTS**: Candidato moderado - Vale a análise")
            else:
                recomendacoes.append("🎯 **BTTS**: Probabilidade baixa - Melhor evitar")
       
        if 'over25' in selected_markets:
            if prob_over25 >= 60:
                recomendacoes.append("⚽ **Over 2.5**: FORTE candidato - Alta chance de gols")
            elif prob_over25 >= 50:
                recomendacoes.append("⚽ **Over 2.5**: Candidato moderado - Boa oportunidade")
            else:
                recomendacoes.append("⚽ **Over 2.5**: Probabilidade baixa - Poucos gols esperados")
       
        if 'over15' in selected_markets:
            if prob_over15 >= 80:
                recomendacoes.append("⚽ **Over 1.5**: FORTE candidato - Muito provável")
            elif prob_over15 >= 70:
                recomendacoes.append("⚽ **Over 1.5**: Candidato moderado - Boa segurança")
            else:
                recomendacoes.append("⚽ **Over 1.5**: Probabilidade moderada - Analisar mais")
       
        if 'under35' in selected_markets:
            if prob_under35 >= 70:
                recomendacoes.append("🛡️ **Under 3.5**: FORTE candidato - Jogo controlado esperado")
            elif prob_under35 >= 60:
                recomendacoes.append("🛡️ **Under 3.5**: Candidato moderado - Baixo risco de muitos gols")
            else:
                recomendacoes.append("🛡️ **Under 3.5**: Probabilidade baixa - Possível jogo aberto")
       
        if 'under25' in selected_markets:
            if prob_under25 >= 60:
                recomendacoes.append("🛡️ **Under 2.5**: FORTE candidato - Poucos gols esperados")
            elif prob_under25 >= 50:
                recomendacoes.append("🛡️ **Under 2.5**: Candidato moderado")
            else:
                recomendacoes.append("🛡️ **Under 2.5**: Probabilidade baixa")
       
        if 'second_half_more' in selected_markets:
            if prob_second_half_more >= 60:
                recomendacoes.append("⏱️ **2nd Half More Goals**: FORTE candidato - Mais gols na segunda parte")
            elif prob_second_half_more >= 50:
                recomendacoes.append("⏱️ **2nd Half More Goals**: Candidato moderado")
            else:
                recomendacoes.append("⏱️ **2nd Half More Goals**: Probabilidade baixa")
           
        return recomendacoes
   
    # --- Funções de Alerta e Relatório (Mantidas) ---
    def send_alert(self, match_info, analise, email_to):
        if not EMAIL_USER or not EMAIL_PASS:
            st.warning("Configure EMAIL_USER e EMAIL_PASS no .env.")
            return
       
        try:
            msg = MimeMultipart()
            msg['From'] = EMAIL_USER
            msg['To'] = email_to
            msg['Subject'] = f"⚽ Value Bet: {match_info['home_team']} vs {match_info['away_team']}"
           
            body = f"""
Partida: {match_info['home_team']} vs {match_info['away_team']} ({match_info['date'].strftime('%d/%m %H:%M')})
Value Bets (baseado em dados reais):
"""
            for market in ['btts', 'over25', 'over15', 'under35', 'under25', 'second_half_more']:
                if market in analise:
                    prob = analise.get(f'prob_{market}', 0)
                    value = calculate_value_bet(prob, 2.0)
                    if value and value > 0.1:
                        body += f"- {market.upper()}: {prob}% prob | Value: {value:.2f}\n"
           
            msg.attach(MimeText(body, 'plain'))
           
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, email_to, msg.as_string())
            server.quit()
            st.success("📧 Alerta enviado com dados reais!")
        except Exception as e:
            st.error(f"Erro no email: {e}")
    def gerar_relatorio_pdf(self, analises):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt="Relatório de Análises Reais", ln=1, align='C')
        pdf.ln(10)
       
        for analise in analises[-10:]:
            pdf.cell(200, 10, txt=f"{analise['home']} vs {analise['away']}", ln=1)
            pdf.cell(200, 10, txt=f"BTTS: {analise['prob_btts']}% | Over 2.5: {analise['prob_over25']}%", ln=1)
            pdf.ln(5)
       
        pdf_bytes = pdf.output(dest='S')
        return pdf_bytes
# --- 5. FUNÇÕES DE VISUALIZAÇÃO MELHORADAS ---
def create_gauge_chart(value, title, target_prob, max_value=100):
    """Cria um gráfico de velocímetro (gauge) mais atraente."""
   
    if value >= target_prob:
        bar_color = '#00FF7F'
        marker_color = 'darkgreen'
    elif value >= target_prob - 10:
        bar_color = '#FFD700'
        marker_color = 'orange'
    else:
        bar_color = '#FF6347'
        marker_color = 'darkred'
       
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = value,
        title = {'text': f"<span style='font-size:1.0em'>{title}</span>"},
        domain = {'x': [0, 1], 'y': [0, 1]},
        gauge = {
            'shape': "angular",
            'axis': {'range': [None, max_value], 'tickwidth': 1, 'tickcolor': "darkblue"},
            'bar': {'color': bar_color},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [0, target_prob - 10], 'color': "rgba(255, 0, 0, 0.2)"},
                {'range': [target_prob - 10, target_prob], 'color': "rgba(255, 255, 0, 0.2)"},
                {'range': [target_prob, max_value], 'color': "rgba(0, 255, 0, 0.2)"}
            ],
            'threshold': {
                'line': {'color': marker_color, 'width': 4},
                'thickness': 0.75,
                'value': value}}))
   
    fig.update_layout(height=200, margin=dict(l=10, r=10, t=50, b=10))
    return fig

# --- NOVA FUNÇÃO: Criar ficha de jogos Under 3.5 / Over 0.5 ---
def display_under_35_over_05_ficha():
    """Exibe uma ficha com 6 jogos recomendados para Under 3.5 e Over 0.5 gols"""
    
    st.markdown("---")
    st.markdown("## 🎯 Ficha de Jogos: Under 3.5 & Over 0.5 Gols")
    st.markdown("### **6 jogos selecionados com alta probabilidade de menos de 4 gols e pelo menos 1 gol**")
    
    with st.spinner("Buscando os melhores jogos para Under 3.5 / Over 0.5..."):
        matches = get_under_35_over_05_matches()
    
    if not matches:
        st.warning("⚠️ Não foram encontrados jogos que atendam aos critérios no momento.")
        return
    
    # Criar 2 colunas para os jogos
    col1, col2 = st.columns(2)
    
    for i, match in enumerate(matches):
        with col1 if i % 2 == 0 else col2:
            # Card do jogo
            with st.container():
                st.markdown(f"### ⚽ {match['home_team']} vs {match['away_team']}")
                
                # Informações básicas
                st.markdown(f"**Competição:** {match['competition']}")
                st.markdown(f"**Data:** {match['date'].strftime('%d/%m %H:%M')}")
                
                # Probabilidades
                prob_col1, prob_col2 = st.columns(2)
                with prob_col1:
                    st.metric(
                        "Under 3.5 Gols", 
                        f"{match['prob_under_35']}%",
                        delta="ALTA" if match['prob_under_35'] >= 75 else "MODERADA"
                    )
                with prob_col2:
                    st.metric(
                        "Over 0.5 Gols", 
                        f"{match['prob_over_05']}%", 
                        delta="ALTA" if match['prob_over_05'] >= 80 else "MODERADA"
                    )
                
                # Estilos dos times
                st.markdown("**Estilos:**")
                style_col1, style_col2 = st.columns(2)
                with style_col1:
                    st.markdown(f"🏠 {match['home_style'].upper()}")
                    st.progress(match['home_attack']/10, text=f"Ataque: {match['home_attack']}/10")
                    st.progress(match['home_defense']/10, text=f"Defesa: {match['home_defense']}/10")
                
                with style_col2:
                    st.markdown(f"🚩 {match['away_style'].upper()}")
                    st.progress(match['away_attack']/10, text=f"Ataque: {match['away_attack']}/10")
                    st.progress(match['away_defense']/10, text=f"Defesa: {match['away_defense']}/10")
                
                # Recomendação
                if match['prob_under_35'] >= 75 and match['prob_over_05'] >= 80:
                    st.success("🎯 **FORTE RECOMENDAÇÃO** - Alto valor esperado")
                elif match['prob_under_35'] >= 70 and match['prob_over_05'] >= 75:
                    st.info("✅ **RECOMENDAÇÃO MODERADA** - Boa oportunidade")
                else:
                    st.warning("⚠️ **ANÁLISE CAUTELOSA** - Verificar odds")
                
                st.markdown("---")
    
    # Legenda e explicação
    st.markdown("""
    ### 📊 Como funciona esta seleção:
    - **Under 3.5 Gols**: Probabilidade >70% de haver menos de 4 gols no jogo
    - **Over 0.5 Gols**: Probabilidade >75% de haver pelo menos 1 gol no jogo
    - **Critério**: Times defensivos têm prioridade na seleção
    - **Atualização**: Dados renovados a cada 30 minutos
    """)
# --- 6. INTERFACE PRINCIPAL ---
def main():
   
    # 1. INICIALIZAÇÃO ROBUSTA DO STATE
    if 'last_analise' not in st.session_state:
        st.session_state['last_analise'] = None
    if 'last_match' not in st.session_state:
        st.session_state['last_match'] = None
    if 'selected_comp_name' not in st.session_state:
         st.session_state['selected_comp_name'] = None
    analisador = AnalisadorAutomatico()
    competitions = get_competitions()
   
    if not competitions:
        # Só exibe erro de API se a chave não for a default e o carregamento falhar
        if FOOTBALL_DATA_API_KEY != "DEFAULT_KEY":
            st.error("❌ Não foi possível carregar as competições. Verifique sua **FOOTBALL\_DATA\_API\_KEY** ou o limite de requisições.")
        return
    # GARANTIA DE COMP. SELECIONADA
    if st.session_state['selected_comp_name'] not in competitions:
         st.session_state['selected_comp_name'] = list(competitions.keys())[0]
    st.title("⚽ Analisador Automático de Apostas")
    st.markdown("### **🤖 Análise Completa** | Dados Reais | H2H | Odds Live | Alertas")
   
    # Mensagem de Status/Configuração
    api_status_col, api_key_col = st.columns([1, 2])
    api_status_col.markdown(f"**🔑 Status APIs:**")
    api_key_col.info(f"Football: **{FOOTBALL_DATA_API_KEY[:8]}...** | Odds: **{ODDS_API_KEY[:8] if ODDS_API_KEY != 'sua_chave_the_odds_api' else '⚠️ Configurar!'}**")
    st.sidebar.header("⚙️ Configurações & Ferramentas")
   
    # --- Sidebar: Configuração da Análise ---
    st.sidebar.subheader("🎯 Mercados & Filtros")
   
    market_map = {
        'btts': 'BTTS (Ambas Marcam)', 'over25': 'Over 2.5 Gols',
        'over15': 'Over 1.5 Gols', 'under35': 'Under 3.5 Gols',
        'under25': 'Under 2.5 Gols', 'second_half_more': 'Mais Gols 2º Tempo'
    }
   
    default_markets_keys = ['btts', 'over25', 'over15', 'under35', 'second_half_more']
    default_markets_display = [market_map[k] for k in default_markets_keys]
   
    selected_markets_display = st.sidebar.multiselect(
        "Mercados Ativos",
        options=list(market_map.values()),
        default=default_markets_display
    )
   
    reverse_market_map = {v: k for k, v in market_map.items()}
    selected_markets = [reverse_market_map[m] for m in selected_markets_display]
   
    risco_filter = st.sidebar.selectbox("Filtro de Recomendações", ["Todos", "🔥 Value Bet (Odd Real > Odd Justa)", "🛡️ Baixo Risco (Prob >70%)"])
   
    st.sidebar.markdown("---")
   
    # --- Sidebar: Watchlist ---
    with st.sidebar.expander("📋 Watchlist & Alertas"):
        new_match = st.text_input("Adicionar Partida (Home vs Away)", key="new_match_input")
        if st.button("Adicionar à Watchlist") and new_match:
            analisador.watchlist.append(new_match)
            st.session_state.watchlist = analisador.watchlist
            st.rerun()
           
        st.markdown("##### Partidas Salvas:")
       
        for i, match in enumerate(analisador.watchlist):
            col1, col2 = st.columns([3, 1])
            col1.write(f"- {match}", key=f"match_{i}")
            if col2.button("X", key=f"rem_{i}"):
                analisador.watchlist.pop(i)
                st.session_state.watchlist = analisador.watchlist
                st.rerun()
       
        if not analisador.watchlist:
            st.info("Sua Watchlist está vazia.")
           
        st.markdown("---")
        email_to = st.text_input("Email para Alertas", value="seu@email.com")
        if st.button("📧 Enviar Alertas de Value"):
             for match_str in analisador.watchlist:
                try:
                    home, away = match_str.split(" vs ")
                    # Simulação de análise para o alerta
                    analise_exemplo = {'prob_btts': 65, 'prob_over25': 70, 'prob_over15': 85, 'prob_under35': 75, 'prob_under25': 50, 'prob_second_half_more': 55}
                    analisador.send_alert({'home_team': home, 'away_team': away, 'date': datetime.now()}, analise_exemplo, email_to)
                except Exception as e:
                    st.error(f"Erro ao enviar alerta para '{match_str}': {e}")
    # --- Tabs de Navegação ---
    tab1, tab2, tab3, tab4 = st.tabs(["🔍 Análise de Partidas", "📊 Perfis de Times", "📈 Histórico & Relatórios", "🎯 Ficha Under 3.5/Over 0.5"])
   
    with tab1:
        st.markdown("## ⚽ Seleção e Análise Automática")
       
        # 1. Seleção de Competição
        comp_col, match_col = st.columns([1, 2])
        with comp_col:
           
            # ATRIBUIÇÃO AO SESSION STATE AQUI!
            selected_comp_name = st.selectbox(
                "Selecione a **Competição**:",
                options=list(competitions.keys()),
                key='comp_select',
                index=list(competitions.keys()).index(st.session_state['selected_comp_name'])
            )
            st.session_state['selected_comp_name'] = selected_comp_name # Atualiza o state
       
        # 2. Seleção de Partida
        competition_id = competitions[selected_comp_name]
       
        with match_col:
            with st.spinner(f"Buscando partidas de {selected_comp_name}..."):
                matches = get_matches(competition_id)
           
            match_options = []
            for match in matches:
                if match["status"] in ["SCHEDULED", "TIMED"]:
                    try:
                        match_date = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
                        match_info = {
                            "id": match["id"],
                            "home_id": match["homeTeam"]["id"],
                            "away_id": match["awayTeam"]["id"],
                            "display": f"🏠 {match['homeTeam']['name']} vs 🚩 {match['awayTeam']['name']} - {match_date.strftime('%d/%m %H:%M')}",
                            "home_team": match["homeTeam"]["name"],
                            "away_team": match["awayTeam"]["name"],
                            "date": match_date
                        }
                        match_options.append(match_info)
                    except:
                        continue
           
            if not match_options:
                st.warning("⚠️ Nenhuma partida futura encontrada.")
                selected_match = None
            else:
                selected_match_str = st.selectbox("Selecione a **Partida** para análise:", options=[m["display"] for m in match_options])
                match_index = [m["display"] for m in match_options].index(selected_match_str)
                selected_match = match_options[match_index]
       
        # 3. Execução da Análise
        if selected_match:
            if st.button("🚀 Iniciar Análise Automática", use_container_width=True):
                with st.spinner(f"🔍 Analisando {selected_match['home_team']} vs {selected_match['away_team']}..."):
                    try:
                        # O uso de fetch_team_profile_cached e fetch_h2h (cacheado) aqui minimiza a API usage!
                        analise = analisador.analisar_partida_automatica(
                            selected_match['home_team'],
                            selected_match['away_team'],
                            selected_comp_name,
                            selected_match['home_id'],
                            selected_match['away_id'],
                            competition_id,
                            selected_markets
                        )
                        st.session_state['last_analise'] = analise
                        st.session_state['last_match'] = selected_match
                        st.success("Análise concluída com sucesso!")
                    except Exception as e:
                        st.error(f"Erro ao executar a análise: {e}")
        # 4. Apresentação dos Resultados (Melhorado)
        if st.session_state['last_analise']:
            analise = st.session_state['last_analise']
            selected_match = st.session_state['last_match']
           
            st.markdown("---")
            st.markdown(f"## ✅ **Resultado da Análise** | {selected_match['home_team']} vs {selected_match['away_team']}")
           
            header_col1, header_col2, header_col3 = st.columns([1, 1, 1])
            header_col1.markdown(f"### 🏠 {selected_match['home_team']}")
            header_col2.metric("Data/Hora", selected_match['date'].strftime('%d/%m %H:%M'))
            header_col3.markdown(f"### 🚩 {selected_match['away_team']}")
            st.markdown("---")
           
            # --- Seção 1: Probabilidades & Odds Justas ---
            st.markdown("### 📊 Probabilidades Calculadas & Odd Justa")
           
            cols_prob = st.columns(len(selected_markets))
            i = 0
            for market in selected_markets:
                prob_key = f'prob_{market}'
                odd_key = f'odd_justa_{market}'
                label = market_map.get(market, market.replace('_', ' ').title())
               
                target_prob = 60
               
                with cols_prob[i]:
                    if prob_key in analise:
                        fig = create_gauge_chart(analise[prob_key], f"{label} (%)", target_prob)
                        st.plotly_chart(fig, use_container_width=True)
                        st.caption(f"**Odd Justa**: {analise[odd_key]}")
                    else:
                        st.warning(f"Dados {label} indisponíveis.")
                i += 1
           
            st.markdown("---")
           
            # --- Seção 2: Recomendações e Detalhes ---
            detail_col, recomend_col = st.columns([2, 1])
           
            with detail_col:
                st.markdown("### 🔍 Análise Detalhada (Perfil e H2H)")
                for linha in analise['analise_detalhada']:
                    st.markdown(f"* {linha}")
                   
                st.markdown("---")
                st.markdown("### 💰 Calculadora de Value Bet")
                with st.expander("Insira as Odds Reais da Casa de Apostas"):
                    value_cols = st.columns(min(3, len(selected_markets)))
                   
                    for j, market in enumerate(selected_markets):
                        with value_cols[j % len(value_cols)]:
                            prob = analise.get(f'prob_{market}', 0)
                            odd_justa = analise.get(f'odd_justa_{market}', 0)
                            label = market_map.get(market, market.replace('_', ' ').title())
                           
                            odd_real = st.number_input(f"Odd **{label}**:", min_value=1.01, value=odd_justa, step=0.01, format="%.2f", key=f"odd_real_{market}")
                            value = calculate_value_bet(prob, odd_real)
                           
                            delta_text = "❌ SEM VALUE"
                            if value and value > 0.05:
                                delta_text = "✅ VALUE BET FORTE!"
                            elif value and value > 0:
                                delta_text = "✅ Value Pequeno"
                            st.metric("Resultado (EV)", f"{value:.3f}", delta=delta_text)
                       
            with recomend_col:
                st.markdown("### 🎯 Recomendações Finais")
                for rec in analise['recomendacao']:
                    st.success(rec)
                   
                st.markdown("---")
                st.markdown("### 💸 Odds em Tempo Real")
                live_odds = analisador.fetch_live_odds(selected_match['home_team'], selected_match['away_team'])
                if live_odds:
                    for bookie in live_odds[:2]:
                        st.subheader(f"{bookie['title']}")
                        # Lógica simplificada para Over/Under 2.5
                        market_totals = next((m for m in bookie.get('markets', []) if m['key'] == 'totals'), None)
                        if market_totals:
                            over_25 = next((o['price'] for o in market_totals['outcomes'] if o.get('point') == 2.5 and o.get('name') == 'Over'), 'N/A')
                            under_25 = next((o['price'] for o in market_totals['outcomes'] if o.get('point') == 2.5 and o.get('name') == 'Under'), 'N/A')
                            st.text(f"Over 2.5: @{over_25} | Under 2.5: @{under_25}")
                        else:
                            st.text("Dados de Totais não disponíveis.")
                else:
                    st.info("Odds API não configurada ou dados não disponíveis.")
    # --- Aba 2: Perfis de Times ---
    with tab2:
        st.markdown("## ⚽ Perfil Dinâmico dos Times (Baseado em Dados Reais)")
       
        if st.session_state['last_match']:
            # Pega IDs da última análise
            home_id = st.session_state['last_match']['home_id']
            away_id = st.session_state['last_match']['away_id']
            comp_id = competitions[st.session_state['selected_comp_name']]
           
            with st.spinner("Carregando perfis dos times..."):
                # CHAMA A FUNÇÃO CACHEADA!
                home_profile = fetch_team_profile_cached(home_id, comp_id)
                away_profile = fetch_team_profile_cached(away_id, comp_id)
           
            home_col, away_col = st.columns(2)
           
            with home_col:
                st.markdown(f"### 🏠 {st.session_state['last_match']['home_team']}")
                st.write(f"**Estilo:** **{home_profile['estilo'].upper()}**")
                st.progress(home_profile['ataque'] / 10, text=f"Ataque: {home_profile['ataque']}/10")
                st.progress(home_profile['defesa'] / 10, text=f"Defesa: {home_profile['defesa']}/10")
                st.markdown(f"* BTTS em jogos recentes: **{home_profile['btts']}%**")
                st.markdown(f"* Over 2.5 em jogos recentes: **{home_profile['over25']}%**")
               
            with away_col:
                st.markdown(f"### 🚩 {st.session_state['last_match']['away_team']}")
                st.write(f"**Estilo:** **{away_profile['estilo'].upper()}**")
                st.progress(away_profile['ataque'] / 10, text=f"Ataque: {away_profile['ataque']}/10")
                st.progress(away_profile['defesa'] / 10, text=f"Defesa: {away_profile['defesa']}/10")
                st.markdown(f"* BTTS em jogos recentes: **{away_profile['btts']}%**")
                st.markdown(f"* Over 2.5 em jogos recentes: **{away_profile['over25']}%**")
        else:
            st.warning("⚠️ Analise uma partida primeiro na aba **Análise de Partidas** para popular os perfis dos times.")
    # --- Aba 3: Histórico e Relatórios ---
    with tab3:
        st.markdown("## 📈 Histórico de Análises & Relatórios")
       
        if analisador.historico_analises:
            df_historico = pd.DataFrame(analisador.historico_analises)
            df_historico['Prob Média'] = (df_historico['prob_btts'] + df_historico['prob_over25']) / 2
           
            st.dataframe(df_historico.sort_values(by='data', ascending=False), use_container_width=True)
           
            st.markdown("---")
            st.markdown("### 📄 Exportar Relatório")
           
            pdf_report = analisador.gerar_relatorio_pdf(analisador.historico_analises)
            st.download_button(
                label="⬇️ Gerar PDF das Últimas 10 Análises",
                data=pdf_report,
                file_name="Relatorio_Analises_Futebol.pdf",
                mime="application/pdf"
            )
        else:
            st.info("O histórico de análises está vazio. Analise uma partida para ver os dados aqui.")
    
    # --- NOVA ABA: Ficha Under 3.5 / Over 0.5 ---
    with tab4:
        display_under_35_over_05_ficha()
if __name__ == "__main__":
    main()
