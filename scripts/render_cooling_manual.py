"""Render the systems-manual explainer as standalone SVG, then PNG via librsvg.

Run from the repository root: python scripts/render_cooling_manual.py
Requires rsvg-convert (librsvg). No browser or image-generation service is used.
"""
from pathlib import Path
from html import escape
import subprocess

OUT = Path(__file__).resolve().parents[1] / 'docs/v1/figures'
TEMPERATURES = [51, 55, 62, 57, 49, 53, 55, 54]
FAN_PATH = 'M10.827 16.379a6.082 6.082 0 0 1-8.618-7.002l5.412 1.45a6.082 6.082 0 0 1 7.002-8.618l-1.45 5.412a6.082 6.082 0 0 1 8.618 7.002l-5.412-1.45a6.082 6.082 0 0 1-7.002 8.618l1.45-5.412Z'
# Fan glyph: Lucide fan, ISC license. See the figure README for attribution.


def render(locale, layout, scenario):
    ko = locale == 'ko'
    def tr(en, kr): return kr if ko else en
    individual = layout == 'individual'
    temperatures = TEMPERATURES.copy()
    if scenario == 'hot': temperatures[2] = 78
    if scenario == 'missing': temperatures[2] = None
    def duty(t): return 0 if t < 50 else 100 if t >= 70 else 30 + (t - 50) * 3.5
    def fmt(value): return f'{value:g}'
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="960" height="940" viewBox="0 0 960 940">',
             '<title>pifanctl cooling systems manual: '+escape(layout+' / '+scenario)+'</title>',
             '<desc>Design illustration with example temperatures. Front fans, rear ports, physical PWM wiring and logical control flow.</desc>',
             '<style>text{font-family:Arial,"Apple SD Gothic Neo",sans-serif;font-size:16px;fill:#20272d}.small{font-size:13px;fill:#69737b}.heading{font-size:24px;font-weight:600}.section{font-size:16px;font-weight:600}.frame{stroke:#d4dade;stroke-width:1.5;fill:none}.board{stroke:#20272d;stroke-width:1;fill:#fff}.port{fill:#eef1f3;stroke:#20272d;stroke-width:1}.wire{stroke:#5a9dd5;stroke-width:1.6;fill:none}.air{stroke:#c59664;stroke-width:1.6;stroke-dasharray:5 4;fill:none}.fan{stroke:#20272d;stroke-width:1;fill:none}.rule{stroke:#d4dade;stroke-width:1}</style>',
             '<rect width="960" height="940" fill="#fff"/>']
    def text(x, y, value, cls='', anchor='start'):
        parts.append(f'<text x="{x}" y="{y}" class="{cls}" text-anchor="{anchor}">{escape(str(value))}</text>')
    def path(d, cls): parts.append(f'<path d="{d}" class="{cls}"/>')
    def fan(cx, cy, radius):
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{radius}" class="fan"/>')
        parts.append(f'<g transform="translate({cx-8} {cy-8}) scale(.667)" stroke="#20272d" stroke-width="1.5" fill="none"><path d="{FAN_PATH}"/></g>')
    text(28, 27, 'PIFANCTL / SYSTEM DESCRIPTION', 'small')
    text(932, 27, tr('21-00 / v1 design','21-00 / v1 설계'), 'small', 'end')
    text(28, 62, tr('Cluster cooling system','클러스터 냉각 계통'), 'heading')
    layout_label = tr('Per-board fans: 8 fans / 8 Pis','보드별 팬: 팬 8개 / Pi 8대') if individual else tr('Shared rack fans: 2 fans / 8 Pis','랙별 공유 팬: 팬 2개 / Pi 8대')
    scenario_label = {'normal':tr('NORMAL','정상'),'hot':tr('pi-03 temperature rise','pi-03 온도 상승'),'missing':tr('pi-03 temperature missing','pi-03 온도 누락'),'watchdog':tr('Operator heartbeat expired','operator heartbeat 만료')}[scenario]
    text(28, 93, layout_label)
    text(932, 93, scenario_label, anchor='end')
    text(28, 137, tr('FIG. 1 / Physical layout: side elevation','FIG. 1 / 물리 배치: 측면도'), 'section')
    text(932, 137, tr('Example values / no live device','예시 값 / 실제 장비 연결 없음'), 'small', 'end')
    for start, ox, group in [(0,28,'rack-a'),(4,508,'rack-b')]:
        w=424
        text(ox, 174, f'Pi {start+1}..{start+4} / '+tr('per-board','개별 냉각') if individual else f'CoolingZone {group}')
        text(ox+w, 174, tr('4 members','4대'),'small','end')
        y0=193; bx=88; end=w-54
        text(ox+18,y0+24,tr('FRONT','전면'),'small')
        text(ox+w-58,y0+24,tr('REAR','후면'),'small')
        path(f'M{ox+78} {y0+44} V{y0+226} H{ox+w-32} V{y0+44} M{ox+78} {y0+44} H{ox+w-32}','frame')
        for i in range(4):
            y=y0+58+i*42; t=temperatures[start+i]
            affected=start+i==2 and scenario in ('hot','missing')
            parts.append(f'<rect x="{ox+bx}" y="{y}" width="{end-bx}" height="27" class="board"'+(' style="fill:#eaf3fa"' if affected else '')+'/>')
            text(ox+bx+8,y+19,f'pi-{start+i+1:02d}')
            text(ox+end-9,y+19,tr('MISSING','누락') if t is None else f'{t} °C',anchor='end')
            parts.append(f'<rect x="{ox+end}" y="{y+6}" width="8" height="15" class="port"/>')
            path(f'M{ox+end+8} {y+13} H{ox+w-23}','frame')
            if individual:
                fan(ox+30,y+14,16)
                path(f'M{ox+48} {y+14} H{ox+78} m-5 -3 l5 3 -5 3','air')
                path(f'M{ox+end+8} {y+20} H{ox+w-14} V{y+33} H{ox+30} V{y+26}','wire')
        if not individual:
            fan(ox+31,y0+136,26)
            for y in (92,142,192): path(f'M{ox+49} {y0+y} H{ox+78} m-5 -3 l5 3 -5 3','air')
            path(f'M{ox+end+8} {y0+78} H{ox+w-14} V{y0+241} H{ox+31} V{y0+155}','wire')
            text(ox+w/2,y0+264,f'worker: pi-{start+1:02d}',anchor='middle')
            text(ox+w/2,y0+284,f'fan-{1 if start==0 else 2:02d} / '+tr('shared PWM','공유 PWM'),anchor='middle')
            values=temperatures[start:start+4]
            unsafe=scenario=='watchdog' or None in values
            maximum=None if unsafe else max(values)
            text(ox,510,f'fan-{1 if start==0 else 2:02d}: {fmt(100 if unsafe else duty(maximum))}% / '+('FAILSAFE' if unsafe else tr('max ','최고 ')+f'{maximum} °C'))
        else:
            text(ox+w/2,y0+264,tr('Each Pi: worker → its own fan','각 Pi의 worker → 자기 팬'),anchor='middle')
            text(ox+w/2,y0+284,tr('Single-node CoolingZone × 4','단일 노드 CoolingZone × 4'),anchor='middle')
            for i in range(4):
                t=temperatures[start+i]
                text(ox+(i%2)*220,510+(i//2)*25,f'fan-pi-{start+i+1:02d}: {fmt(100 if scenario=="watchdog" or t is None else duty(t))}%')
    path('M28 564 H56','wire'); text(65,569,tr('PWM wiring','PWM 배선'),'small')
    path('M190 564 H218','air'); text(227,569,tr('Airflow','공기 흐름'),'small')
    text(340,569,tr('Flat boards / rear-facing ports','평평한 보드 / 후면 포트'),'small')
    messages={
      'normal':tr('NORMAL / Each fan follows its own board.','NORMAL / 각 팬은 자기 보드의 온도를 따릅니다.') if individual else tr('NORMAL / Each fan follows the hottest member in its zone.','NORMAL / 각 공유 팬은 자기 구역의 최고 온도를 따릅니다.'),
      'hot':tr('HIGH TEMP / Only pi-03 fan: 100%.','HIGH TEMP / pi-03의 팬만 100%.') if individual else tr('HIGH TEMP / rack-a: 100%. rack-b unaffected.','HIGH TEMP / rack-a 공유 팬 100%. rack-b 영향 없음.'),
      'missing':tr('DATA LOST / Only pi-03 fan: 100%. Other fans regulate normally.','DATA LOST / pi-03의 팬 100%. 다른 팬 정상 제어.') if individual else tr('DATA LOST / rack-a: 100%. rack-b regulates normally.','DATA LOST / rack-a 공유 팬 100%. rack-b 정상 제어.'),
      'watchdog':tr('WATCHDOG EXPIRED / All fans remain at 100%.','WATCHDOG EXPIRED / 모든 worker가 팬을 100%로 유지.')}
    text(28,602,messages[scenario]); path('M28 623 H932','rule')
    text(28,653,tr('FIG. 2 / Logical configuration and control signals','FIG. 2 / 논리 구성과 제어 신호'),'section')
    for x,title,value in [(28,tr('① SELECT MEMBERS','① 대상 선택'),tr('Node labels / names','Node 라벨 / 이름')),(340,tr('② COOLING GROUP','② 냉각 구역'),'CoolingZone'),(650,tr('③ ASSIGN ACTUATORS','③ 물리 팬 지정'),'Fan / fanRefs')]:
        text(x,681,title,'small'); text(x,708,value)
    text(290,703,'→'); text(605,703,'→')
    text(28,741,tr('Config: YAML / ConfigMap / CRD → operator → node plan → worker','설정: YAML / ConfigMap / CRD → operator → 노드별 plan → worker'))
    text(28,769,tr('Temperature: Node agents → Prometheus → worker → PWM','온도: Node agent → Prometheus → worker → PWM'))
    path('M28 788 H932','rule'); text(28,817,tr('FIG. 3 / Automatic control sequence','FIG. 3 / 자동 제어 순서'),'section')
    unsafe=scenario in ('missing','watchdog')
    steps=[('01 / SELECT',tr('1 board per fan','노드 1대씩 선택') if individual else tr('4 members per zone','구역별 노드 4대 선택')),
           ('02 / VERIFY',tr('Missing pi-03 sample','pi-03 샘플 없음') if scenario=='missing' else tr('Heartbeat expired','heartbeat 만료') if scenario=='watchdog' else tr('Data and plan valid','온도·설정 유효')),
           ('03 / COMPUTE',tr('Safety check failed','안전 조건 실패') if unsafe else tr('Maximum temperature','최고 온도 계산')),
           ('04 / COMMAND',tr('Affected fans: 100%','영향받은 팬 100%') if unsafe else tr('Curve → PWM duty','제어 곡선 → PWM'))]
    for i,(title,value) in enumerate(steps):
        text(28+i*235,846,title,'small'); text(28+i*235,872,value)
    text(28,918,tr('Design example / steady-state target duty / down-ramp omitted / not measured RPM','설계 예시 / 정상상태 목표 duty / 하강 지연 생략 / RPM 측정값 아님'),'small')
    parts.append('</svg>')
    return '\n'.join(parts)+'\n'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for locale in ('en','ko'):
        for layout in ('rack','individual'):
            for scenario in ('normal','hot','missing','watchdog'):
                path=OUT/f'{layout}-{scenario}-{locale}.svg'
                path.write_text(render(locale,layout,scenario))
                subprocess.run(['rsvg-convert','--zoom','2','--output',str(path.with_suffix('.png')),str(path)],check=True)
    print('Rendered 16 SVG originals and 16 PNG figures (1920 × 1880).')

if __name__=='__main__': main()
