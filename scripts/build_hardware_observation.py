"""Rebuild the public passive-observation chart and PDF from anonymous records."""
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs/v1/hardware-verification'


def build(charts=True, pdf=True):
    if charts:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        with (DATA / 'passive-transitions.csv').open() as f:
            events = [(float(r['elapsed_seconds']), int(r['output_level'])) for r in csv.DictReader(f)]
        from analyze_gpio_observation import analyze
        summary = json.loads((DATA / 'passive-summary.json').read_text())
        measured = analyze(events)
        for field in ('complete_cycles', 'median_cycle_hz', 'median_observed_high_percent'):
            if abs(measured[field] - summary[field]) > 1e-6: raise ValueError('Summary/data mismatch')
        cycles = [(events[i][0], 1 / (events[i+2][0] - events[i][0]))
                  for i in range(len(events)-2) if events[i][1] == 1]
        plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False, 'svg.hashsalt': 'pifanctl-hardware-observation'})
        fig, axes = plt.subplots(2, 1, figsize=(9, 6), layout='constrained')
        first = [(t, level) for t, level in events if t <= .008]
        axes[0].step([t*1000 for t, level in first], [level for t, level in first], where='post', color='#27677c')
        axes[0].set(xlabel='Elapsed time (ms)', ylabel='Observed GPIO level', yticks=[0, 1],
                    title='A. First 8 ms: digital levels at the SoC, not connector voltage')
        axes[1].scatter([t for t, hz in cycles], [hz for t, hz in cycles], s=2, alpha=.3, color='#27677c')
        axes[1].axhline(1000, color='#bd5c31', linestyle='--', label='Configured software PWM: 1,000 Hz')
        axes[1].axhline(measured['median_cycle_hz'], color='#364152', label=f"Observed median: {measured['median_cycle_hz']:.2f} Hz")
        axes[1].set(xlabel='Elapsed time (s)', ylabel='Observed cycle frequency (Hz)', ylim=(0, 1500),
                    title='B. Userspace observations: missed edges and observer load are possible')
        axes[1].legend(fontsize=8, loc='lower right')
        fig.savefig(DATA / 'passive-observation.png', dpi=180)
        svg = DATA / 'passive-observation.svg'
        fig.savefig(svg, metadata={'Date': None})
        svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
        plt.close(fig)
    if not pdf: return
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
    styles = getSampleStyleSheet(); styles['BodyText'].spaceAfter = 9
    output = ROOT / 'output/pdf/pifanctl-hardware-verification.pdf'
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=(8.27*inch,11.69*inch),
                            rightMargin=40,leftMargin=40,topMargin=40,bottomMargin=42)
    story = []
    def paragraph(text, style='BodyText'): story.append(Paragraph(text, styles[style]))
    paragraph('pifanctl: Hardware Verification', 'Title')
    paragraph('NF-A12x25 PWM / Pi 4 shared-fan rack / 1.1.0 runtime', 'Heading2')
    paragraph('INTERIM REPORT: PHYSICAL ACCEPTANCE NOT ACHIEVED', 'Heading3')
    paragraph('This report records a bounded read-only GPIO observation. It does not certify connector-level PWM, electrical safety, measured RPM, airflow or cooling capacity.')
    rows = [['Observation', 'Result'], ['Duration / complete cycles', '10.00001 s / 8,432'],
            ['Configured / median observed frequency', '1,000 Hz / 892.54 Hz'],
            ['Commanded / median observed HIGH ratio', '35.04% / 36.59%'],
            ['Median / p99 sampling gap', '2.95 / 7.56 microseconds'],
            ['Maximum sampling gap', '38.28 ms: missed edges possible'],
            ['Tach pulses / existing bias', '0 / pull-down: inconclusive'],
            ['Pin configuration / worker', 'Unchanged / Ready, no restart']]
    table=Table(rows,colWidths=[240,275]);table.setStyle(TableStyle([
      ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#16394a')),
      ('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
      ('FONTSIZE',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
      ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.whitesmoke,colors.white])]))
    story.extend([table,Spacer(1,14)])
    story.append(Image(str(DATA/'passive-observation.png'),width=515,height=343))
    paragraph('Clock: userspace monotonic transition observations. Long gaps and CPU observer effects prevent calibrated jitter claims. SoC levels do not establish cable continuity or connector voltage.')
    story.append(PageBreak())
    paragraph('Remaining procedure and acceptance gates','Heading1')
    for title, body in [
      ('01. Electrical inspection','Confirm supply, common ground, tach continuity and Pi-safe voltage. Identify adapters and any external pull-up. Do not enable bias until the input is verified.'),
      ('02. Conforming PWM','Noctua specifies a 25 kHz target, acceptable 21-28 kHz. Validate the actual connector voltage, duty, polarity and frequency. The current software 1 kHz path does not establish this contract; no kernel PWM chip is currently exposed to the worker.'),
      ('03. Hardware PWM handoff','Review the Pi 4 overlay and actual chip/channel mapping. Preserve single-writer ownership, independent cooling, resource identity and rollback. A hardware driver change requires controlled immutable-Fan replacement. Do not guess channels or relabel software PWM as hardware PWM.'),
      ('04. Tach baseline','After wiring passes, enable optional feedback with the verified BCM input, appropriate 3.3 V bias and two pulses/revolution. Record 60 s of fresh pulse counts, RPM, requested duty and member temperatures without changing cooling policy.'),
      ('05. Duty/RPM sweep','Use one managed writer for 100%, 75%, 50% and 30% stages. Settle at least 30 s, accounting for the falling-duty limiter, and observe 60 s per stage. Verify an independent local deadline/temperature guard first. Abort at any member reaching 60 C, stale telemetry, collector errors or lost observation. Restore normal policy on every exit.'),
      ('06. Broader physical scope','Startup/shutdown, reboot, power loss, network partition, Pi 5 actuation, full v0 rollback and larger-fleet capacity remain unverified. They require their own physical setup and safeguards. Existing failed thermal holds remain unchanged.')]:
        paragraph(title,'Heading2');paragraph(body)
    paragraph('Acceptance ledger: GPIO observation completed. Connector PWM, usable tach baseline, duty/RPM response and the broader physical matrix remain NOT MEASURED / NOT RUN. No fan stop, load trial or reduced-duty sweep was performed here.')
    paragraph('Sources and reproducibility','Heading2')
    paragraph('Noctua PWM specifications: https://www.noctua.at/pub/media/wysiwyg/Noctua_PWM_specifications_white_paper.pdf<br/>Linux PWM interface: https://docs.kernel.org/driver-api/pwm.html<br/>Project tracking: github.com/jyje/pifanctl/issues/69 and /64')
    paragraph('Anonymous CSV/summary and the complete procedure are in docs/v1/hardware-verification/. Rebuild with scripts/build_hardware_observation.py. The collector is read-only, bounded and specific to the reviewed Pi 4 pin mapping.')
    def footer(canvas, document):
        canvas.setFont('Helvetica',8);canvas.setFillColor(colors.grey)
        canvas.drawString(40,25,'pifanctl | Hardware evidence / interim observation')
        canvas.drawRightString(555,25,str(document.page))
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    print(output)


if __name__ == '__main__':
    build(charts='--pdf-only' not in sys.argv, pdf='--chart-only' not in sys.argv)
