# src/lybt_sim/analysis.py
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from . import config

def analyze_results(aerodrome, fleet, scenario):
    print("\n" + "=" * 80)
    print(f" ANALIZA REZULTATA: {scenario['name']}")
    print("=" * 80)

    # Convert to DataFrame
    df_results = pd.DataFrame(aerodrome.waiting_times)

    if len(df_results) > 0:
        # --- FIX: Handle missing arrival_time column ---
        # If the engine doesn't provide it, we use 'wait_time' as a proxy 
        # or check if it's named 'start_time' or 'entry_time'
        time_col = 'arrival_time' if 'arrival_time' in df_results.columns else None
        
        print(f"\n OSNOVNE METRIKE:")
        print(f"   • Ukupno vreme: {aerodrome.current_time/60:.1f} min")
        print(f"   • Broj sletelih: {len(aerodrome.landed_aircraft)}/{len(fleet)}")
        print(f"   • Prosecno cekanje: {df_results['wait_time'].mean()/60:.1f} min")
        
        # Critical PhD Metric: Fuel Safety
        exhausted = len(df_results[df_results['remaining_fuel'] <= 5]) # 0kg or close to it
        print(f"   • KRITICNO (0kg goriva): {exhausted} vazduhoplova ⚠️")

        if time_col:
            t_change = config.T_CHANGE_SEC
            df_vfr = df_results[df_results[time_col] < t_change]
            df_ifr = df_results[df_results[time_col] >= t_change]
            print(f"   • VFR Prosek: {df_vfr['wait_time'].mean()/60:.1f} min")
            print(f"   • IFR Prosek: {df_ifr['wait_time'].mean()/60:.1f} min")

    create_visualizations(df_results, scenario, aerodrome.current_time)

def create_visualizations(df_results, scenario, total_time):
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(15, 10))

    plt.subplot(2, 2, 1)
    if len(df_results) > 0:
        plt.bar(df_results['aircraft_id'], df_results['wait_time']/60)
        plt.xlabel('ID Aviona')
        plt.ylabel('Vreme cekanja (min)')
        plt.title('Vreme cekanja po avionu')
        plt.grid(True, alpha=0.3)

    plt.subplot(2, 2, 2)
    if len(df_results) > 0:
        plt.hist(df_results['wait_time']/60, bins=10, edgecolor='black', alpha=0.7)
        plt.xlabel('Vreme cekanja (min)')
        plt.ylabel('Broj aviona')
        plt.title('Distribucija vremena cekanja')
        plt.grid(True, alpha=0.3)

# Plot 3: Wait Time vs. Arrival Time (Scatter)
    plt.subplot(2, 2, 3)
    if len(df_results) > 0:
        plt.scatter(df_results['arrival_time']/60, df_results['wait_time']/60, 
                    c=(df_results['arrival_time'] > config.T_CHANGE_SEC), cmap='coolwarm')
        plt.axvline(x=config.T_CHANGE_SEC/60, color='r', linestyle='--', label='Weather Change')
        plt.xlabel('Vreme dolaska (min)')
        plt.ylabel('Vreme cekanja (min)')
        plt.title('Uticaj promene vremena na kasnjenje')
        plt.legend()

    # Plot 4: Fuel Status Distribution
    plt.subplot(2, 2, 4)
    if 'fuel_status' in df_results.columns:
        fuel_counts = df_results['fuel_status'].value_counts()
        fuel_counts.plot(kind='bar', color=['green', 'orange', 'red'])
        plt.title('Status goriva pri sletanju')

    plt.suptitle(f'Rezultati simulacije: {scenario["name"]}', fontsize=16)
    plt.tight_layout()

    out = config.RESULTS_DIR / f"rezultati_{scenario['id']}.png"
    plt.savefig(out, dpi=150, bbox_inches='tight')
    print(f"Grafikoni sacuvani: {out}")
