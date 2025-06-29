import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from cycler import cycler
import numpy as np
import pandas as pd

from aiohttp_client_cache import CachedSession, SQLiteBackend
import asyncio

from inspect import getsourcefile
from pathlib import Path

import re
from pprint import pprint
from collections import defaultdict
import json

import csv
import io

#######################################
# mmolb stat history by dusk (@1ug1a) #
#######################################

# config stuff!

# STAT_MODE: decides what gets graphed. 'Batter', 'Pitcher', 'Batters', or 'Pitchers'.
STAT_MODE = 'Batters' 
MEAN_TYPE = 'Rolling'
# ID: make sure to use a player ID for 'Batter'/'Pitcher' mode, and a team ID for 'Batters'/'Pitchers'.
ID = '6806c6869edf4f7b46032b9a'

# TIME_START, TIME_END: format: (season, day)
TIME_START = (1, 0)
TIME_END = (2, 120)

# ROLLING_WINDOW: controls the size of the rolling window, in # of games.
ROLLING_WINDOW = 20

# TEAM_BATTER_STAT, TEAM_PITCHER_STAT: the stat that gets tracked.
TEAM_BATTER_STAT = 'ops'
TEAM_PITCHER_STAT = 'era'

# USE_CUSTOM_COLORS, CUSTOM_COLORS: lets you choose a custom set of line colors for your graph.
USE_CUSTOM_COLORS = False
CUSTOM_COLORS = '#7F3C8D,#11A579,#3969AC,#F2B701,#E73F74,#80BA5A,#E68310,#008695,#CF1C90,#f97b72,#4b4b8f,#A5AA99'.split(',')

# MAX_CONNECTIONS: the number of simultaneous API requests that can be active at a time. please don't overload freecashe.ws
MAX_CONNECTIONS = 4

# USE_SOLO_CUSTOM_STATS, SOLO_CUSTOM_STATS: vestigial, unused as of current ver
USE_SOLO_CUSTOM_STATS = False
SOLO_CUSTOM_STATS = ['ops', 'era']

##################################################################
# don't change anything below unless you know what you're doing! #
##################################################################

# SOLO_BATTING_STATS, SOLO_PITCHING_STATS: stats you can choose from (and show up in the individual-player stat mode). don't touch this!
SOLO_BATTING_STATS = ['ba', 'obp', 'slg', 'ops', 'babip', 'bb_p', 'k_p', 'sb_p']
SOLO_PITCHING_STATS = ['era', 'fip_r', 'whip', 'h9', 'hr9', 'k9', 'bb9', 'kpbb']

# cache stuff
SCRIPT_PATH = Path(getsourcefile(lambda: 0)).resolve()
DB_PATH = SCRIPT_PATH.parent / 'MMOLBStatHistory.db'
CACHE = SQLiteBackend(
  cache_name=DB_PATH,  # For SQLite, this will be used as the filename
  expire_after=60*25,                         
)

# custom color handler
CYCLER = cycler(color=CUSTOM_COLORS) if USE_CUSTOM_COLORS else None

# x-tick stuff
XTICK_OPTIONS = MaxNLocator(nbins=15, integer=True, prune=None, steps=[1, 2, 4, 5, 10])

async def get_url(session, url, format, semaphore):
  async with semaphore:
    async with session.get(url) as response:
      return await response.json() if format == 'json' else await response.text()

async def get_urls(session, urls, format, max_con_req=1):
  match urls:
    case str():
      url_list = [urls]
    case dict():
      url_list = urls.values()
    case list():
      url_list = urls
  semaphore = asyncio.Semaphore(max_con_req)
  tasks = [get_url(session, url, format, semaphore) for url in url_list]
  result = await asyncio.gather(*tasks)
  match urls:
    case str():
      return result[0]
    case dict():
      return dict(zip(urls.keys(), result))
    case list():
      return result

cashews_stat_filters = [
  'at_bats',
  'caught_stealing',
  'doubles',
  'earned_runs',
  'hit_batters',
  'hit_by_pitch',
  'hits_allowed',
  'home_runs',
  'home_runs_allowed',
  'outs',
  'plate_appearances',
  'sac_flies',
  'singles',
  'stolen_bases',
  'strikeouts',
  'struck_out',
  'triples',
  'walked',
  'walks',
]

async def cashews_get_chron(session, kind, ids):
  print(f'Getting {kind} info... ', end='')
  ids = ','.join(ids) if not isinstance(ids, str) else ids
  api_url = f'https://freecashe.ws/api/chron/v0/entities?kind={kind}&id={ids}'
  response = await get_urls(session, api_url, 'json')
  response = [response['items'][idx]['data'] for idx in range(0, len(response['items']))]
  print('Done!')
  return response[0] if len(response) == 1 else response

async def cashews_get_stat_history(session, kind, id, time_start, time_end, is_greater_league, mean_type):
  print('Obtaining stat history... ', end='')
  url = f'https://freecashe.ws/api/stats?{kind}={id}&start={time_start[0]},{time_start[1]}&end={time_end[0]},{time_end[1]}&group=player,day&fields={','.join(cashews_stat_filters)}'
  response = await get_urls(session, url, 'csv')
  time_list = create_time_list(time_start, time_end)
  api_data = csv_to_stats_dict(response, time_list)
  #pprint(api_data)
  print('Done!')
  return api_data

def csv_to_stats_dict(csv_string, time_list):
  file = io.StringIO(csv_string)
  reader = csv.DictReader(file)
  temp_dict = [row for row in reader]
  stats_dict = defaultdict(dict)
  fill_stats = defaultdict(dict)
  for time in time_list:
    for row in temp_dict:
      #print(row)
      stat_time = (int(row['season']), int(row['day']))
      id = row['player_id']
      if stat_time == time:
        fill_stats[id] = {stat: int(value) for stat, value in row.items() if stat not in ['season', 'day', 'player_id']}
      stats_dict[id][time] = fill_stats[id]
  return dict(stats_dict)

def parse_statistics(history_dict):
  print('Parsing statistics... ', end='')
  statistics = defaultdict(dict)
  for player_id, history in history_dict.items():
    for time, stats in history.items():
      statistics[player_id][time] = (parse_batting_stats(stats), parse_pitching_stats(stats))
  print('Done!')
  return dict(statistics)

def create_time_list(time_start, time_end):
  time_list = []
  for season in range(time_start[0], time_end[0]+1):
    season_day_start = time_start[1] if time_start[1] != 0 and season == time_start[0] else 0
    season_day_end = time_end[1] if season == time_end[0] else 239
    for day in range(season_day_start, season_day_end+1):
      time_list.append((season, day))
  return time_list

def parse_batting_stats(stats):
  _pa   = stats.get('plate_appearances', 0)
  _ab   = stats.get('at_bats', 0)
  _1b   = stats.get('singles', 0)
  _2b   = stats.get('doubles', 0)
  _3b   = stats.get('triples', 0)
  _hr   = stats.get('home_runs', 0)
  _h    = _1b + _2b + _3b + _hr
  _bb   = stats.get('walked', 0)
  _hbp  = stats.get('hit_by_pitch', 0)
  _k    = stats.get('struck_out', 0)
  _sf   = stats.get('sac_flies', 0)
  _sb   = stats.get('stolen_bases', 0)
  _cs   = stats.get('caught_stealing', 0)

  ba    = _h / _ab if _ab != 0 else np.nan
  obp   = (_h + _bb + _hbp) / _pa if _pa != 0 else np.nan
  slg   = (_1b + 2*_2b + 3*_3b + 4*_hr) / _ab if _ab != 0 else np.nan
  ops   = obp + slg
  babip = (_h - _hr) / (_ab - _hr - _k + _sf) if (_ab - _hr - _k + _sf) != 0 else np.nan
  bb_p  = _bb / _pa if _pa != 0 else np.nan
  k_p   = _k / _pa if _pa != 0 else np.nan
  sb_p  = _sb / (_sb + _cs) if (_sb + _cs) != 0 else np.nan

  stats_dict = {}
  stats_used = list(set(SOLO_BATTING_STATS) & set(SOLO_CUSTOM_STATS)) if USE_SOLO_CUSTOM_STATS else SOLO_BATTING_STATS
  for i in stats_used:
    stats_dict[i] = locals()[i]

  return stats_dict

def parse_pitching_stats(stats):
  _ip   = stats.get('outs', 0)/3
  _h    = stats.get('hits_allowed', 0)
  _hr   = stats.get('home_runs_allowed', 0)
  _k    = stats.get('strikeouts', 0)
  _bb   = stats.get('walks', 0)
  _er   = stats.get('earned_runs', 0)
  _hb   = stats.get('hit_batters', 0)
  
  era   = 9*_er / _ip if _ip != 0 else np.nan
  fip_r = (13*_hr + 3*(_bb + _hb) - 2*_k) / _ip if _ip != 0 else np.nan
  whip  = (_h + _bb) / _ip if _ip != 0 else np.nan
  h9    = 9*_h / _ip if _ip != 0 else np.nan
  hr9   = 9*_hr / _ip if _ip != 0 else np.nan
  k9    = 9*_k / _ip if _ip != 0 else np.nan
  bb9   = 9*_bb / _ip if _ip != 0 else np.nan
  kpbb  = _k / _bb if _bb != 0 else np.nan

  stats_dict = {}
  stats_used = list(set(SOLO_PITCHING_STATS) & set(SOLO_CUSTOM_STATS)) if USE_SOLO_CUSTOM_STATS else SOLO_PITCHING_STATS
  for i in stats_used:
    stats_dict[i] = locals()[i]

  return stats_dict

def parse_feed(feed, valid_players, disp_start, disp_end):
  parsed_feed = {}
  valid_date = False
  for idx, entry in enumerate(feed):
    entry = feed[idx]
    season, day = entry['season'], entry['day']

    if type(day) == int:
      day = int(day)
      if season == disp_start[0]:
        valid_date = day >= disp_start[1]
      elif season == disp_end[0]:
        valid_date = day <= disp_end[1]
      else:
        valid_date = True

    query_conditions = [
      entry['type'] == 'augment',
      'Special Delivery' in entry['text'],
      'Shipment' in entry['text']
    ]
    if valid_date and any(query_conditions) and any(name in entry['text'] for name in valid_players):
      time = (entry['season'], entry['day'])
      if time not in parsed_feed: 
        parsed_feed[time] = process_entry(entry['text'], valid_players)
      else:
        parsed_feed[time] += ' ' + process_entry(entry['text'], valid_players)
  return parsed_feed

def process_entry(text, valid_players):
  for name in valid_players:
    text = text.replace(name, name.replace('.', '*'))
  split_text = text.split('.')
  new_sentences = []
  for sentence in split_text:
    for name in valid_players:
      if name.replace('.', '*') in sentence:
        new_sentence = sentence.replace('*', '.').lstrip()
        try:
          new_sentence = new_sentence[new_sentence.index('!')+2:]
        except:
          pass
        new_sentences.append(new_sentence)
  return '. '.join(new_sentences) + '.'

def parse_player_dict(team_info):
  players = team_info['Players']
  player_dict = defaultdict()
  for player in players:
    player_id = player.pop('PlayerID')
    player.pop('Stats')
    player_dict[player_id] = player
  return dict(player_dict)

def plot_graph(stat_mode, mean_type, rolling_window, stats, team_info, feed, player_dict, valid_ids, time_start, time_end, league):
  player_ids = valid_ids
  player_names = [f"{player_dict[id]['FirstName']} {player_dict[id]['LastName']}" for id in player_ids]
  player_labels = {id: f"{player_dict[id]['Slot']} {player_dict[id]['FirstName']} {player_dict[id]['LastName']}" for id in player_ids}
  
  match stat_mode:
    case 'Batters' | 'Batter':
      stat = TEAM_BATTER_STAT
      stat_index = 0
    case 'Pitchers' | 'Pitcher':
      stat = TEAM_PITCHER_STAT
      stat_index = 1
  
  len_stats = len(stats[next(iter(stats))])
  time_units = range(0, len_stats)
  time_list = create_time_list(time_start, time_end)
  plots = {}
  for id, history in stats.items():
    if id in valid_ids:
      plots[id] = [value[stat_index][stat] for value in history.values()]
  #print(len_stats)
  #print(len(stat_lines[next(iter(stat_lines))]))

  means = {}
  for id in valid_ids:
    means[id] = pd.Series(plots[id]).rolling(window=ROLLING_WINDOW, min_periods=1).mean()

  # start plotting
  fig, ax = plt.subplots(layout="constrained", figsize=(12, 6))
  ax.set_prop_cycle(CYCLER)

  for id in player_ids:
    ax.plot(time_units, means[id], label = player_labels[id])
    #print(id)

  t_name = f'{team_info['Location']} {team_info['Name']}'

  ax.set_xlabel('Day')
  ax.set_xlim(left=0, right=len_stats-1)
  ax.set_xticks(time_units)
  ax.set_xticklabels(time_list)
  ax.set_title(f'{t_name} {stat_mode[:-3] + "ing"} History ({stat.upper()}) - {rolling_window} Day {mean_type} Average (S{time_start[0]}D{time_start[1]:03}-S{time_end[0]}D{time_end[1]:03})')
  ax.grid(which='major', color='#999999', linewidth=0.8)
  ax.grid(which='minor', color='#CCCCCC', linestyle=':', linewidth=0.5)
  ax.minorticks_on()
  ax.legend()

  ax.xaxis.set_major_locator(XTICK_OPTIONS)

  #print(feed)
  cmap = plt.get_cmap("tab10")
  for time_unit, actual_time in enumerate(stats[next(iter(stats))]):
    #print(time_unit, actual_time)
    if isinstance(actual_time[1], int) and (actual_time in feed):
      names_found = [name in feed.get(actual_time, '') for name in player_names]
      if names_found.count(True) > 1:
        ax.axvline(x=time_unit, color='black', linestyle='--')
      else:
        i = names_found.index(True)
        #print(i)
        ax.axvline(x=time_unit, color=cmap(i), linestyle='--')

  plt.show()

async def main():
  async with CachedSession(cache=CACHE) as session:
    match STAT_MODE:
      case 'Pitcher' | 'Batter':
        player_info = await cashews_get_chron(session, 'player', ID)
        team_id = player_info['TeamID']
      case 'Pitchers' | 'Batters':
        team_id = ID

    team_info = await cashews_get_chron(session, 'team', team_id)
    player_dict = parse_player_dict(team_info)
    valid_ids = [id for id, info in player_dict.items() if info['PositionType'] == STAT_MODE[:-1]] if STAT_MODE in ['Pitchers', 'Batters'] else [ID]
    valid_names = [f"{player_dict[id]['FirstName']} {player_dict[id]['LastName']}" for id in valid_ids]
    feed = parse_feed(team_info['Feed'], valid_names, TIME_START, TIME_END)
    is_greater_league = team_info['League'] in ['6805db0cac48194de3cd3fe4', '6805db0cac48194de3cd3fe5']
    team_stat_history = await cashews_get_stat_history(session, 'team', team_id, TIME_START, TIME_END, is_greater_league, MEAN_TYPE)
    team_statistics = parse_statistics(team_stat_history)
    for time, entry in feed.items():
      print(f"{team_info['Emoji']} Season {time[0]}, {'Day ' if type(time[1]) == int else ''}{time[1]}: {entry}")
    plot_graph(STAT_MODE, MEAN_TYPE, ROLLING_WINDOW, team_statistics, team_info, feed, player_dict, valid_ids, TIME_START, TIME_END, team_info['League'])

if __name__ == '__main__':
  asyncio.run(main())