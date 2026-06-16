"""
master CSV(또는 업로드 xlsx) → 단일 HTML 대시보드 생성기
사용: python build_dashboard.py <input.csv|input.xlsx> [output.html]
  - 입력이 마스터 CSV(g2b_accumulator.py 산출물)면 한글헤더 자동 인식
  - 입력이 원본 xlsx면 '숨김_물품전체_로우데이타' 시트에서 추출
규칙: 최종납품요구여부='Y'만 집계, 제조사=물품식별명 2번째 항목

[물품식별번호 추가/관리]
  같은 폴더의 watchlist.csv 에 적힌 물품식별번호만 골라 보여줍니다.
  새 제품을 추적하려면 watchlist.csv 맨 아래에 한 줄 추가:  물품식별번호,제조사,제품명
  (제조사·제품명은 비워두면 데이터에서 자동으로 채워집니다)
  watchlist.csv 가 없으면 수집된 전체를 그대로 사용합니다.
"""
import sys, json, os, csv as _csv

WATCHLIST = "watchlist.csv"

def load_watchlist():
    """{식별번호:(제조사override,제품명override)} 반환. 파일 없으면 None(전체사용)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), WATCHLIST)
    if not os.path.exists(path):
        return None
    wl = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in _csv.DictReader(f):
            idnt = str(row.get('물품식별번호', '')).strip()
            if not idnt or idnt.startswith('#'):
                continue
            wl[idnt] = (str(row.get('제조사', '') or '').strip(),
                        str(row.get('제품명', '') or '').strip())
    return wl

def parse_idnm(s):
    if s and ',' in str(s):
        p=[x.strip() for x in str(s).split(',')]
        return (p[1] if len(p)>=2 else '기타', p[2] if len(p)>=3 else '')
    return ('기타','')

def from_xlsx(path):
    import openpyxl
    wb=openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws=wb['숨김_물품전체_로우데이타']
    out=[]
    for i,r in enumerate(ws.iter_rows(values_only=True)):
        if i<2 or not r[1] or r[26]!='Y': continue
        d=str(r[6] or '')
        if len(d)<8: continue
        mn,prod=parse_idnm(r[15])
        out.append(dict(rno=str(r[1]),sno=str(r[3]),date=d,y=d[:4],m=int(d[4:6]),
            inst=str(r[5] or ''),sido=str(r[36] or ''),corp=str(r[9] or ''),
            manu=mn,prod=prod,idnt=str(r[14] or ''),dtl=str(r[13] or ''),
            qty=float(r[40] or 0),uprc=float(r[38] or 0),amt=float(r[41] or 0)))
    return out

def from_csv(path):
    import csv
    out=[]
    with open(path,encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            if row.get('최종납품요구여부','Y')!='Y': continue
            d=str(row.get('납품요구접수일자') or row.get('납품요구결재일자') or '')
            if len(d)<8: continue
            mn,prod=parse_idnm(row.get('물품식별명',''))
            def num(k):
                try: return float(row.get(k) or 0)
                except: return 0.0
            out.append(dict(rno=str(row.get('납품요구번호','')),sno=str(row.get('납품요구물품순번','')),
                date=d,y=d[:4],m=int(d[4:6]),inst=str(row.get('수요기관명','')),
                sido=str(row.get('수요기관지역명') or row.get('수요기관소재시도') or ''),
                corp=str(row.get('업체명','')),manu=mn,prod=prod,
                idnt=str(row.get('물품식별번호','')),dtl=str(row.get('세부품명','')),
                qty=num('수량') or num('납품수량'),uprc=num('단가') or num('납품단가'),
                amt=num('금액') or num('납품금액')))
    return out

def main():
    if len(sys.argv)<2:
        print('usage: python build_dashboard.py <input.csv|input.xlsx> [output.html]'); sys.exit(1)
    inp=sys.argv[1]
    out=sys.argv[2] if len(sys.argv)>2 else 'dashboard.html'
    recs = from_xlsx(inp) if inp.lower().endswith(('.xlsx','.xlsm')) else from_csv(inp)

    # ── watchlist 적용: 등록된 물품식별번호만 선별 + 제조사/제품명 보정 ──
    wl = load_watchlist()
    wl_meta = []
    if wl is not None:
        # 필터 전, 데이터에서 관측되는 라벨 확보(빈 watchlist 칸 자동채움용)
        seen_label = {}
        for x in recs:
            seen_label.setdefault(x['idnt'], (x['manu'], x['prod']))
        tracked_manu = {v[0] for v in wl.values() if v[0]}
        candidates = {}
        for x in recs:
            if x['idnt'] not in wl and x['manu'] in tracked_manu:
                candidates.setdefault(x['idnt'], (x['manu'], x['prod']))
        cnt = {}
        kept = []
        for x in recs:
            if x['idnt'] not in wl:
                continue
            mo, po = wl[x['idnt']]
            if mo: x['manu'] = mo
            if po: x['prod'] = po
            kept.append(x)
            cnt[x['idnt']] = cnt.get(x['idnt'], 0) + 1
        recs = kept
        # 관리 패널용 메타: watchlist.csv 순서 유지, 0건 번호 포함
        for idnt, (mo, po) in wl.items():
            fm, fp = seen_label.get(idnt, ('', ''))
            wl_meta.append(dict(idnt=idnt, manu=mo or fm, prod=po or fp, cnt=cnt.get(idnt, 0)))
        print(f"watchlist 적용: {len(wl)}개 등록 식별번호 기준 {len(recs)}건 선별 "
              f"(실적 있는 번호 {sum(1 for m in wl_meta if m['cnt']>0)}개)")
        if candidates:
            print(f"※ 추적 제조사의 미등록 신규 식별번호 {len(candidates)}건 (watchlist.csv 추가 검토, 상위 일부):")
            for idnt,(mn,po) in sorted(candidates.items())[:12]:
                print(f"    {idnt},{mn},{po}")
            if len(candidates)>12:
                print(f"    ...외 {len(candidates)-12}건")

    recs.sort(key=lambda x:x['date'], reverse=True)

    # 자사(한싹) 항상 포함 + 추적 제조사 순서
    seen=[]
    for x in recs:
        if x['manu'] not in seen: seen.append(x['manu'])
    order=['한싹']+[m for m in ['소만사','수산아이앤티','모니터랩','엑스게이트','플랜티넷','엔토빌소프트'] if m in seen]
    order+=[m for m in seen if m not in order]
    colors={'한싹':'#D7263D','소만사':'#16386E','수산아이앤티':'#2E78C7','모니터랩':'#3BA39B',
            '엑스게이트':'#C68A3A','플랜티넷':'#8466B5','엔토빌소프트':'#7A8794'}
    palette=['#5B6B7C','#9AA7B4','#476A8E','#6E8CAD','#A9744F','#5D8A78']
    pi=0
    for m in order:
        if m not in colors:
            colors[m]=palette[pi%len(palette)]; pi+=1

    years=sorted(set(x['y'] for x in recs))
    meta=dict(period=f"{recs[-1]['date']}~{recs[0]['date']}" if recs else '',
              total=len(recs), years=years, order=order, colors=colors,
              latest=recs[0]['date'] if recs else '', watchlist=wl_meta)

    tmpl=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'template.html'),encoding='utf-8').read()
    html=tmpl.replace('/*__DATA__*/','window.RECORDS='+json.dumps(recs,ensure_ascii=False)+';') \
             .replace('/*__META__*/','window.META='+json.dumps(meta,ensure_ascii=False)+';')
    open(out,'w',encoding='utf-8').write(html)
    print(f'생성 완료: {out}  (레코드 {len(recs)}건, 제조사 {len(order)}곳)')

if __name__=='__main__':
    main()
