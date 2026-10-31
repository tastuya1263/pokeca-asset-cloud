#!/usr/bin/env python3
"""Daily quote updater. Only authorized X API and user-provided CSV feeds."""
import os,json,csv,re,statistics,datetime,urllib.request,urllib.parse,pathlib,io
ROOT=pathlib.Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
CAT=DATA/'catalog.json'; OUT=DATA/'prices.json'; HIST=DATA/'history.json'
now=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec='seconds')
products=json.loads(CAT.read_text(encoding='utf-8'))
old=json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
history=json.loads(HIST.read_text(encoding='utf-8')) if HIST.exists() else []
quotes={p['id']: {'x':[],'mercari':[],'snkrdunk':[]} for p in products}
problems=[]
# User-provided legally obtained feed from URL or local file.
# Format: id,source,price,price_type,url,observed_at; source x|mercari|snkrdunk; type buy_offer|sold|ask.
feed=os.getenv('AUTHORIZED_PRICE_CSV_URL','').strip()
if feed:
 try:
  if not feed.startswith('https://'): raise ValueError('Only HTTPS URL permitted')
  req=urllib.request.Request(feed,headers={'User-Agent':'PokeAssetTracker/1.0'})
  content=urllib.request.urlopen(req,timeout=20).read(3_000_000).decode('utf-8-sig')
  reader=csv.DictReader(io.StringIO(content))
  for r in reader:
   pid=r.get('id','').strip(); source=r.get('source','').strip().lower(); kind=r.get('price_type','').strip()
   if pid not in quotes or source not in quotes[pid]:continue
   if (source=='x' and kind!='buy_offer') or (source in ('mercari','snkrdunk') and kind!='sold'):continue
   price=int(float(r['price']))
   if 100<=price<=2000000:
    quotes[pid][source].append({'price':price,'url':r.get('url',''),'observed_at':r.get('observed_at',''), 'type':kind,'origin':'authorized_csv'})
 except Exception as e:problems.append('Authorized CSV: '+str(e))
# X official recent search - explicit price posts only, restricted to configured seller accounts.
token=os.getenv('X_BEARER_TOKEN','').strip()
accounts=[x.strip().lstrip('@') for x in os.getenv('X_SELLER_ACCOUNTS','').split(',') if x.strip()]
if token and accounts:
 for p in products:
  try:
   handles=' OR '.join('from:'+a for a in accounts[:12]); q='"'+p['name']+'" ('+handles+') -is:retweet'
   url='https://api.x.com/2/tweets/search/recent?'+urllib.parse.urlencode({'query':q,'max_results':20,'tweet.fields':'created_at,author_id'})
   request=urllib.request.Request(url,headers={'Authorization':'Bearer '+token,'User-Agent':'PokeAssetTracker/1.0'})
   result=json.loads(urllib.request.urlopen(request,timeout=15).read().decode('utf-8'))
   for t in result.get('data',[]):
    body=t.get('text',''); match=re.search(r'(?:買取(?:価格|金額)?|買取強化)[^\n¥￥0-9]{0,16}[¥￥]?\s*([0-9][0-9,]{2,})\s*円?',body)
    if not match:continue
    amount=int(match.group(1).replace(',',''))
    if 100<=amount<=2000000:
     quotes[p['id']]['x'].append({'price':amount,'url':'https://x.com/i/web/status/'+t['id'],'observed_at':t.get('created_at',''), 'type':'buy_offer','origin':'official_x_api'})
  except Exception as e:problems.append('X '+p['id']+': '+str(e)[:160])
else: problems.append('X API: token or seller accounts not configured')
results={}
for p in products:
 pid=p['id']; entries={}; all_quotes=[]
 for source, observations in quotes[pid].items():
  if observations:
   values=[x['price'] for x in observations]; med=int(statistics.median(values)); entries[source]={'price':med,'count':len(values),'type':'buy_offer' if source=='x' else 'sold','samples':observations[:12]}; all_quotes.append(med)
  else: entries[source]={'price':None,'count':0,'type':'buy_offer' if source=='x' else 'sold','samples':[]}
 previous=old.get('products',{}).get(pid,{})
 # Never silently carry old quotes into today's fresh average.
 results[pid]={'sources':entries,'reference_average':round(statistics.mean(all_quotes)) if all_quotes else None,'source_count':len(all_quotes),'previous_average':previous.get('reference_average')}
record={'updated_at':now,'products':results,'warnings':problems,'method':'equal-weight mean of available source medians; X buy offers versus marketplace sold prices are different market types'}
OUT.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
summary={'date':now[:10],'prices':{k:v['reference_average'] for k,v in results.items()}}
history=[h for h in history if h.get('date')!=summary['date']]+[summary]
HIST.write_text(json.dumps(history[-365:],ensure_ascii=False,indent=2),encoding='utf-8')
print('Updated',now,'matched products',sum(v['source_count']>0 for v in results.values()),'warnings',len(problems))
