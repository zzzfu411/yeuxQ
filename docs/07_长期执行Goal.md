# 07 闀挎湡鎵ц Goal: A 鑲℃棩棰戝皬棰濆疄鐩樺噯澶囩郴缁?
> 椋庨櫓鎻愮ず: 杩欎釜 goal 鐨勭洰鏍囨槸瀹炵洏鍑嗗,涓嶆槸绔嬪嵆瀹炵洏銆傛湰椤圭洰涓嶄細鑷姩鎻愪氦鐪熷疄 broker 璁㈠崟銆?
## 鐩爣

鎶?Quantify 闀挎湡鎺ㄨ繘涓?A 鑲℃棩棰戦噺鍖栧伐浣滃彴:

```text
鏁版嵁瀹¤ -> 绋冲仴鎬х爺绌?-> 妯℃嫙鐩樻棩鎶?-> LLM 椋庢帶瀹℃煡 -> 浜哄伐瀹℃壒 -> micro_live_ready
```

`micro_live_ready` 鍙〃绀烘潗鏂欏噯澶囧畬姣?浠嶇劧鍙兘浜哄伐鍐崇瓥鍜屼汉宸ヤ笅鍗曘€?
## 姣忓懆鑺傚

- 鍛ㄤ竴: 璺戞暟鎹璁°€?- 鍛ㄤ簩: 璺戠爺绌跺拰绋冲仴鎬у疄楠屻€?- 鍛ㄤ笁: 璺?LLM 瀹℃煡鍜屾ā鎷熺洏鏃ユ姤銆?- 鍛ㄥ洓: 淇鏁版嵁銆佺瓥鐣ャ€侀鎺ф垨鎵ц闂銆?- 鍛ㄤ簲: 鐢熸垚 readiness 鏉愭枡鍜屽懆澶嶇洏銆?
## 鍛戒护閾?
鎺ㄨ崘姣忓懆鍏堣窇鐪熷疄鏁版嵁鍚姩妫€鏌?鍐嶈窇涓€閿绾挎祦姘寸嚎:

```powershell
uv run python examples/run_recent_data_plan.py --config config/research_recent.yaml --output-dir results/bootstrap_recent --as-of 2026-06-08
uv run python examples/run_real_data_bootstrap.py --config config/research_recent.yaml --output-dir results/bootstrap_recent --min-symbols 300 --as-of 2026-06-08
uv run python examples/run_weekly_pipeline.py --config config/research_recent.yaml --review-stage paper --paper-state-dir results/paper/core --wf-train-days 120 --wf-test-days 60 --wf-step-days 60
```

娴佹按绾夸細鑷姩鐢熸垚鐪熷疄鏁版嵁 bootstrap銆佺爺绌舵姤鍛娿€佽繎鏈熺湡瀹炴暟鎹棬銆佹暟鎹璁°€佸競鍦虹姸鎬併€佺ǔ鍋ユ€ф姤鍛娿€亀alk-forward銆佸€欓€夌瓥鐣?walk-forward銆佸€欓€夌瓥鐣ュ垎琛屾儏楠岃瘉銆佸€欓€夌瓥鐣ョ瓫閫夈€佹ā鎷熺洏鏃ユ姤銆佹ā鎷熺洏绋冲畾鎬у鏌ャ€丩LM-ready 纭畾鎬у鏌ャ€丩LM prompt銆佸懆搴﹀鐩樺拰绛栫暐妗ｆ蹇収銆傚畠榛樿涓嶈皟鐢ㄥ閮?LLM銆佷笉鍐欎汉宸ュ鎵硅褰曘€佷笉鐢熸垚鐪熷疄 broker 鎸囦护銆傛湭鎻愪緵杩炵画 paper 鐘舵€佺洰褰曟椂,`paper_stability.json` 浼氭槑纭?BLOCK銆?
濡傛灉闇€瑕侀€愭鎺掓煡,鍙互鎸変笅闈㈠懡浠ら摼鍒嗘璺戙€?
濡傛灉 AKShare 鎴栬鎯呮帴鍙ｈ缃戠粶/鏉冮檺闄愬埗鎸′綇,浣跨敤绂荤嚎 CSV 鍚堝悓琛ラ綈鐪熷疄鏁版嵁鍏ュ彛:

```powershell
uv run python examples/write_data_export_request.py --config config/research_recent.yaml --output-dir data_exports --min-symbols 300
uv run python examples/write_candidate_hypotheses.py --config config/research_recent.yaml --output-dir results\first_million --as-of 2026-06-08
uv run python examples/write_candidate_experiment_queue.py --config config/research_recent.yaml --output-dir results\first_million --as-of 2026-06-08
uv run python examples/run_data_gap_action_plan.py --data-dir data_exports --config config/research_recent.yaml --output-dir results\first_million --min-symbols 300 --as-of 2026-06-08
uv run python examples/write_data_source_qa.py --config config/research_recent.yaml --output-dir data_exports --min-symbols 300 --as-of 2026-06-08
uv run python examples/write_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --output-dir data_exports
uv run python examples/run_data_source_qa_worksheet_preflight.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output-dir data_exports
uv run python examples/write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
uv run python examples/write_data_source_qa_answers.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest
uv run python examples/run_data_source_qa_review.py --checklist data_exports\data_source_qa.json --answers data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --output-dir results\import\source_qa
uv run python examples/write_data_export_templates.py --output-dir data_exports
uv run python examples/normalize_vendor_bars.py --input "<raw-vendor-bars.csv>" --output-dir data_exports --start 2024-06-03 --end 2026-06-05 --min-symbols 300
uv run python examples/convert_tdx_day.py --input-dir "<tdx-vipdoc-or-lday-dir>" --output-dir data_exports --start 2024-06-03 --end 2026-06-05
uv run python examples/run_data_import_doctor.py --data-dir data_exports --config config/research_recent.yaml --output-dir results\import\doctor
uv run python examples/run_offline_data_package.py --data-dir data_exports --config config\research_recent.yaml --output-dir results\first_million --source-qa-answers data_exports\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --as-of 2026-06-08 --min-symbols 300
uv run python examples/run_offline_data_intake.py --raw-bars-csv "<raw-vendor-bars.csv>" --data-dir data_exports --config config/research_recent.yaml --output-dir results\import\offline_intake --source-qa-answers data_exports\data_source_qa_answers.json --source-vendor "<vendor-or-broker>" --source-terminal "<terminal-name>" --source-operator "<operator>" --source-exported-at "<local-time>" --source-price-adjustment qfq --source-price-adjustment-evidence "<evidence>" --source-license-evidence "<evidence>" --source-point-in-time-evidence "<evidence-or-non-pit-note>" --source-reviewed-by "<name>" --source-reviewed-at "<date>" --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
uv run python examples/run_goal_status.py --report-dir results\goal --config config/research_recent.yaml --source-qa-dir results\import\source_qa --import-doctor-dir results\import\doctor --offline-intake-dir results\import\offline_intake --as-of 2026-06-08 --starting-capital 100000 --target-capital 1000000 --years 8 --min-symbols 300 --min-trading-days 240
uv run python examples/run_first_million_pipeline.py --config config/research_recent.yaml --data-dir data_exports --output-dir results\first_million --raw-bars-csv "<raw-vendor-bars.csv>" --source-vendor "<vendor-or-broker>" --source-terminal "<terminal-name>" --source-operator "<operator>" --source-exported-at "<local-time>" --source-price-adjustment qfq --source-price-adjustment-evidence "<evidence>" --source-license-evidence "<evidence>" --source-point-in-time-evidence "<evidence-or-non-pit-note>" --source-reviewed-by "<name>" --source-reviewed-at "<date>" --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
uv run python examples/validate_research_csv.py --bars-csv data_exports\bars.csv --stock-info-csv data_exports\stock_info.csv --fundamentals-csv data_exports\fundamentals.csv --calendar-csv data_exports\calendar.csv --suspensions-csv data_exports\suspensions.csv --index-constituents-csv data_exports\index_constituents.csv --start 2024-06-03 --end 2026-06-05 --min-symbols 300 --output-dir results\import\recent_csv_validation
uv run python examples/import_research_csv.py --cache .\data_cache\research_recent.db --bars-csv data_exports\bars.csv --stock-info-csv data_exports\stock_info.csv --fundamentals-csv data_exports\fundamentals.csv --calendar-csv data_exports\calendar.csv --suspensions-csv data_exports\suspensions.csv --index-constituents-csv data_exports\index_constituents.csv --validate --start 2024-06-03 --end 2026-06-05 --min-symbols 300 --output-dir results\import\recent_csv
```

璇﹁ [09_绂荤嚎鐪熷疄鏁版嵁瀵煎叆鍚堝悓.md](09_绂荤嚎鐪熷疄鏁版嵁瀵煎叆鍚堝悓.md)銆傜绾垮鍏ラ€氳繃鍚?浠嶅繀椤婚噸鏂拌窇 `real_data_bootstrap` 鍜?`data_audit`銆?

Blocked first-million runs should be worked from
`first_million_resolution_plan.json/md/csv`. The plan groups P0 source QA
worksheet rows, required source evidence attachments, and CSV export
replacement tasks before any P2 candidate or capital-goal work. Refresh it with:

```powershell
uv run python examples/run_first_million_resolution_plan.py --report-dir results\first_million --as-of 2026-06-10
```

This file is an operator queue only. It does not change deterministic gates,
does not approve paper or micro-live work, and does not authorize broker orders.

鍏堣窇鐮旂┒:

```powershell
uv run python examples/run_research.py --config config/research.yaml
```

瀵规姤鍛婄洰褰曡窇鏁版嵁瀹¤:

```powershell
uv run python examples/run_recent_data_plan.py --config config/research_recent.yaml --output-dir results/research/<timestamp>
uv run python examples/run_real_data_bootstrap.py --config config/research_recent.yaml --output-dir results/research/<timestamp>
uv run python examples/run_real_data_gate.py --config config/research_recent.yaml --output-dir results/research/<timestamp>
uv run python examples/run_data_coverage.py --config config/research_recent.yaml --output-dir results/research/<timestamp>
uv run python examples/run_data_audit.py --config config/research_recent.yaml --output-dir results/research/<timestamp>
```

璺戠ǔ鍋ユ€у疄楠?

```powershell
uv run python examples/run_robustness.py --config config/research.yaml --output-dir results/research/<timestamp>
uv run python examples/run_walk_forward.py --config config/research.yaml --output-dir results/research/<timestamp>
uv run python examples/run_candidate_walk_forward.py --config config/research.yaml --output-dir results/research/<timestamp>
uv run python examples/run_candidate_regime_validation.py --config config/research.yaml --output-dir results/research/<timestamp>
```

鐢熸垚妯℃嫙鐩樻棩鎶?

```powershell
uv run python examples/run_paper_candidate_plan.py --report-dir results/research/<timestamp> --config config/research_recent.yaml --paper-state-dir results/paper/core
uv run python examples/run_paper_loop.py --config config/research_recent.yaml --state-dir results/paper/core --candidate core_multifactor
uv run python examples/run_paper_stability.py --paper-dir results/paper/core
uv run python examples/run_paper_daily.py --report-dir results/research/<timestamp>
uv run python examples/run_target_plan.py --config config/research.yaml --output-dir results/research/<timestamp> --current-positions results/research/<timestamp>/paper_positions.csv
```

璺?LLM-ready 瀹℃煡:

```powershell
uv run python examples/run_llm_review.py --report-dir results/research/<timestamp> --stage micro_live_ready
```

鐢熸垚甯傚満鐘舵€佸拰鍊欓€夌瓥鐣ョ瓫閫?

```powershell
uv run python examples/run_market_regime.py --config config/research.yaml --output-dir results/research/<timestamp>
uv run python examples/run_candidate_selection.py --config config/research.yaml --output-dir results/research/<timestamp> --starting-capital 100000 --target-capital 1000000 --years 8
```

鍐欎汉宸ュ鎵硅褰?

```powershell
uv run python examples/run_readiness.py --report-dir results/research/<timestamp> --approved-by "your-name" --approval-notes "manual review only"
uv run python examples/run_capital_scaling_plan.py --report-dir results/research/<timestamp> --current-capital 100000 --proposed-capital 120000
```

鐢熸垚鍛ㄥ害澶嶇洏:

```powershell
uv run python examples/run_weekly_review.py --report-dir results/research/<timestamp>
```

## 浜х墿

- `real_data_bootstrap.json/md`: 鐪熷疄鏁版嵁鍚姩妫€鏌?姹囨€荤紦瀛樺瓨鍦ㄦ€с€佹牱鏈媶鍒嗐€乨emo 椋庨櫓銆佽繎鏈熺湡瀹炴暟鎹棬銆佽鐩栫巼鍜屼笅涓€姝ュ懡浠ゃ€?- `recent_data_acquisition_plan.json/md`: 杩戞湡鐪熷疄 A 鑲℃暟鎹噰闆嗚鍒掑拰褰撳墠 BLOCK 鍘熷洜銆?- `data_gap_action_plan.json/md`: 鏁版嵁缂哄彛琛屽姩娓呭崟,鎶?source QA銆丆SV 妯℃澘銆佸繀濉厓鏁版嵁銆乮mport doctor 鍜屼笅涓€姝ュ懡浠ゆ眹鎬诲埌涓€涓彲鎵ц娓呭崟銆?- `candidate_hypotheses.json/md`: 鍊欓€夌瓥鐣ュ亣璁剧洰褰?璁板綍姣忎釜鍊欓€夌殑鐮旂┒鍋囪銆侀€傜敤琛屾儏銆侀獙璇侀棬妲涖€佽嚜鍔ㄩ檷绾ф潯浠躲€乸aper 瑙傚療瑕佹眰鍜岀姝㈠姩浣? 瀹冧笉鏄瓥鐣ユ帓鍚?涔熶笉鏄疄鐩樻寚浠ゃ€?- `candidate_experiment_queue.json/md`: 鍊欓€夌瓥鐣ラ娉ㄥ唽瀹為獙闃熷垪,璁板綍楠岃瘉椤哄簭銆佸懡浠ら摼銆佹垚鍔熸爣鍑嗐€佽瘉浼祴璇曘€佸仠姝㈡潯浠跺拰浜х墿; 瀹冧笉鑳芥彁楂樹换浣曞€欓€夌殑瀹℃煡缁撹銆?- `price_volume_defensive`: 閫氳揪淇℃垨鍒稿晢鏃ョ嚎鍙彁渚?OHLCV 鏃朵紭鍏堥獙璇佺殑鍊欓€?涓嶄娇鐢ㄤ及鍊?璐ㄩ噺瀛楁,浣嗕粛蹇呴』閫氳繃 source QA銆乷ffline intake銆佹暟鎹璁°€佺ǔ鍋ユ€у拰妯℃嫙鐩橀棬妲? 缂哄皯 PIT 璐㈠姟瀛楁鏃?浼板€?璐ㄩ噺渚濊禆鍊欓€変細鍦?`candidate_selection` 涓鏁版嵁渚濊禆闂ㄩ檷绾с€?- `candidate_experiment_readiness.json/md`: 鍊欓€夊疄楠屽彲杩愯鎬у鏌?鍙湁 source QA銆乷ffline intake 鍜屽疄楠岄槦鍒楅兘 PASS 鏃舵墠鍏佽鎸夐娉ㄥ唽闃熷垪鍚姩鍊欓€夊疄楠屻€?- `candidate_experiment_launch.json/md`: 鍊欓€夊疄楠屽惎鍔ㄨ鍒?鍦?readiness PASS 鍚庨攣瀹氶涓€欓€夈€佽繍琛?ID銆佸疄楠岀洰褰曘€佸懡浠ら摼鍜?required outputs; readiness BLOCK 鏃跺彧璁板綍闃诲鍘熷洜銆?- `candidate_experiment_completion.json/md`: 鍊欓€夊疄楠屽畬鎴愬鏌?纭鍚姩璁″垝瑕佹眰鐨勪骇鐗╁瓨鍦ㄤ笖鏃?BLOCK,闃叉鍙寫閫夊ソ鐪嬬殑閮ㄥ垎缁撴灉杩涘叆 paper銆?- `run_manifest.json/md`: 杩愯璇佹嵁娓呭崟,璁板綍閰嶇疆鍝堝笇銆佺紦瀛樺搱甯屻€丆SV 鏁版嵁鎸囩汗銆乺aw vendor 鏂囦欢鎸囩汗銆佹牱鏈獥鍙ｃ€佽偂绁ㄦ暟銆佷氦鏄撴棩鏁板拰瀹夊叏杈圭晫銆?- `real_data_gate.json/md`: 杩戞湡鐪熷疄鏁版嵁闂ㄣ€?- `data_coverage.json/md/csv`: 姣忓彧鑲＄エ瑕嗙洊鑼冨洿銆佺己鍙ｅ拰杩囨湡璇婃柇銆?- `data_audit.json/md`: 鏁版嵁鍙俊搴﹀璁°€?- `market_regime.json/md`: 鏈湴琛屾儏甯傚満鐘舵€佹娴嬨€?- `robustness_report.json/md`: 鍙傛暟鎵板姩鍜屾垚鏈帇鍔涙祴璇曘€?- `walk_forward_report.json/md`: 婊氬姩绐楀彛绋冲畾鎬ч獙璇併€?- `candidate_walk_forward_report.json/md`: 鍊欓€夌瓥鐣ユ粴鍔ㄧ獥鍙ｇǔ瀹氭€ф瘮杈冦€?- `candidate_factor_diagnostics.json/md`: 鍊欓€夌瓥鐣ュ洜瀛愮粍浠惰瘖鏂?妫€鏌ユ槸鍚﹁繃搴︿緷璧栧崟涓€鍥犲瓙銆傚懆娴佹按绾块粯璁よ瘖鏂綋鍓?best candidate銆?- `candidate_regime_validation_report.json/md`: 鍊欓€夌瓥鐣ユ寜甯傚満鐘舵€佸垎妗剁殑绋冲畾鎬ч獙璇併€?- `candidate_selection.json/md/csv`: 鍊欓€夌瓥鐣ユ帓鍚嶅拰璧勯噾鐩爣鍖归厤銆?- `paper_candidate_plan.json/md`: 鍊欓€夎繘鍏ヨ繛缁ā鎷熺洏瑙傚療鐨勯棬绂佽鍒掑拰鏈湴 paper loop 鍛戒护銆?- `capital_goal_status.json/md`: 绗竴妗堕噾鐩爣鎬绘帶闈㈡澘,姹囨€绘暟鎹€佺ǔ鍋ユ€с€佸€欓€夌瓥鐣ャ€佹ā鎷熺洏銆佸鎵瑰拰鏅嬬骇璇佹嵁; raw vendor CSV 璺緞涓嬭繕浼氱敤 `raw_vendor_traceability` 纭 normalization銆乮mport metadata銆丼QLite metadata 鍜?run manifest 鐨勫師濮嬫枃浠舵寚绾逛竴鑷淬€?- `first_million_readiness.json/md`: 绗竴妗堕噾灏辩华鍗＄墖,鎶婃暟鎹己鍙ｃ€乻ource QA銆乷ffline intake銆佸€欓€夊疄楠岄棴鐜拰璧勯噾鐩爣鎬绘帶姹囨垚棣栧睆 PASS/WATCH/BLOCK銆?- `capital_scaling_plan.json/md`: 璧勯噾閫掑瀹℃煡,闄愬埗姣忔璧勯噾鎻愰珮鐨勬渶澶у箙搴︺€?- `paper_state.json`: 妯℃嫙鐩樼姸鎬併€?- `paper_orders.csv`: 妯℃嫙璁㈠崟銆?- `paper_positions.csv`: 鏈€鏂版ā鎷熸寔浠撱€?- `paper_daily.csv`: 杩炵画妯℃嫙鐩樻瘡鏃ョ姸鎬併€?- `paper_stability.json/md`: 杩炵画妯℃嫙鐩樼ǔ瀹氭€у鏌ャ€?- `paper_daily_review.md`: 妯℃嫙鐩樻棩鎶ャ€?- `target_portfolio.json/md/csv`: 涓嬩竴娆＄洰鏍囩粍鍚堝拰鎵嬪伐宸鍙傝€冦€?- `approval_record.json`: 浜哄伐瀹℃壒璁板綍銆?- `micro_live_readiness.json/md`: 灏忛瀹炵洏鍑嗗闂ㄧ粨璁恒€?- `risk_budget.json`: 鎵嬪伐闃舵椋庨櫓棰勭畻銆?- `manual_trade_sheet.csv`: 浜哄伐鍙傝€冭〃,浼樺厛鏉ヨ嚜鐩爣缁勫悎璁″垝,鍖呭惈娴佸姩鎬с€佸弬涓庣巼銆丼T/閫€甯?鍋滅墝/娑ㄨ穼鍋滅瓑椋庨櫓鏍囪; 褰撳墠鎸佷粨鍗充娇琚洰鏍囪偂绁ㄦ睜杩囨护涔熶細淇濈暀涓轰汉宸ュ鐞嗚,涓嶆槸鐪熷疄璁㈠崟銆?- `weekly_review.json/md`: 鍛ㄥ害璇佹嵁鐭╅樀鍜岀户缁?闄嶇骇/鏆傚仠缁撹銆?- `weekly_pipeline.json/md`: 涓€閿祦姘寸嚎闃舵璁板綍鍜屾渶缁堝懆搴︾粨璁恒€?- `strategy_registry_snapshot.json/md`: 褰撳墠鍛ㄧ瓥鐣ユ。妗堝揩鐓с€?- `results/strategy_registry/strategy_registry.json/md`: 闀挎湡鍊欓€夌瓥鐣ュ巻鍙叉。妗?鍖呭惈鍊欓€夌瓥鐣?walk-forward 绋冲畾鎬ц瘉鎹€?- `strategy_promotion_review.json/md`: 瀵圭収璧勯噾鐩爣璺緞鍜屽€欓€夌瓥鐣?walk-forward 鐨勭瓥鐣ユ檵绾у鏌ャ€?
## 鍗囩骇闂?
杩涘叆 `micro_live_ready` 鍓嶅繀椤绘弧瓒?

- 杩戞湡鐪熷疄鏁版嵁闂ㄦ病鏈?BLOCK銆?- 鐪熷疄鏁版嵁 bootstrap 娌℃湁 BLOCK銆?- 鐪熷疄鏁版嵁閫氳繃瀹¤銆?- 绋冲仴鎬ф祴璇曟病鏈?BLOCK銆?- 婊氬姩绐楀彛楠岃瘉娌℃湁 BLOCK銆?- 鍊欓€夌瓥鐣ユ粴鍔ㄧ獥鍙ｉ獙璇佹病鏈?BLOCK銆?- 鍊欓€夌瓥鐣ュ垎琛屾儏楠岃瘉娌℃湁 BLOCK銆?- LLM deterministic review 娌℃湁 BLOCK銆?- 妯℃嫙鐩樼姸鎬佸瓨鍦ㄤ笖涓嶈繛鎺?broker銆?- 杩炵画妯℃嫙鐩樼ǔ瀹氭€ф病鏈?BLOCK銆?- 鐩爣缁勫悎璁″垝鍙緭鍑轰汉宸ュ弬鑰冭〃,涓嶇敓鎴?broker 鎸囦护銆?- 鐩爣缁勫悎璁″垝娌℃湁 ST銆侀€€甯傘€佸仠鐗屻€佹定璺屽仠鎴栫己浠风瓑闃绘柇鎵ц鏍囪; 浣庢祦鍔ㄦ€с€侀珮鍙備笌鐜囨垨楂樻潈閲嶆爣璁拌嚦灏戣Е鍙?WATCH銆?- 鏈変汉宸ュ鎵硅褰曘€?- `manual_trade_sheet.csv` 鍙綔涓轰汉宸ュ弬鑰冦€?
浠讳綍 BLOCK 閮戒細闄嶇骇鍥?research 鎴?paper銆?
## 鍛ㄥ害鍐崇瓥

`weekly_review` 鍙仛姹囨€诲拰闄嶇骇,涓嶅仛涔愯鍗囩骇:

- `continue_paper`: 鏍稿績璇佹嵁閮?PASS,缁х画妯℃嫙鐩樿瀵熴€?- `research_only`: 娌℃湁 BLOCK,浣嗕粛鏈?WATCH 鎴?readiness 璇佹嵁涓嶈冻,缁х画鐮旂┒鍜岃ˉ瀹為獙銆?- `pause_and_fix`: 鏈?BLOCK銆佹牳蹇冭瘉鎹己澶辨垨 broker 杈圭晫琚牬鍧?鏆傚仠鎺ㄨ繘骞朵慨澶嶃€?
瀹冧笉浼氱敓鎴愮湡瀹?broker 鎸囦护,涔熶笉鑳借瘉鏄庣瓥鐣ユ湭鏉ョǔ瀹氳禋閽便€?
## 绛栫暐妗ｆ

姣忔鍊欓€夌瓥鐣ョ瓫閫夊悗,绯荤粺浼氭妸缁撴灉杩藉姞鍒伴暱鏈?registry:

```powershell
uv run python examples/update_strategy_registry.py --report-dir results/research/<timestamp>
```

闀挎湡绛栫暐涓嶈兘鍙嚟鍗曟鍥炴祴鏅嬬骇銆傝嚦灏戣鐪?

- 澶氭瑙傚療涓?PASS/WATCH/BLOCK 鐨勫垎甯冦€?- 骞冲潎鏀剁泭鏄惁鎺ヨ繎璧勯噾鐩爣璺緞銆?- 骞冲潎鍥炴挙鏄惁浣庝簬棰勭畻銆?- 澶忔櫘銆佹嫆鍗曠巼銆佹崲鎵嬫槸鍚︾ǔ瀹氥€?- demo 鏁版嵁瑙傚療鍜岀湡瀹炴暟鎹瀵熷繀椤诲垎寮€鐞嗚В銆?
Registry 鐨勬檵绾ц祫鏍艰鍒?

- demo-only 鍘嗗彶姘歌繙涓嶈兘鏅嬬骇銆?- 鑷冲皯闇€瑕?3 娆＄湡瀹炴暟鎹瀵熴€?- 鑷冲皯闇€瑕?2 娆＄湡瀹炴暟鎹?PASS銆?- 鐪熷疄鏁版嵁鍘嗗彶涓笉鑳藉嚭鐜?BLOCK銆?- 鑷冲皯闇€瑕?3 娆＄湡瀹炴暟鎹€欓€夌瓥鐣?walk-forward 瑙傚療銆?- 鑷冲皯闇€瑕?2 娆＄湡瀹炴暟鎹€欓€夌瓥鐣?walk-forward PASS銆?- 鍊欓€夌瓥鐣?walk-forward 涓嶈兘鍑虹幇 BLOCK,骞冲潎绐楀彛 PASS 姣斾緥涓嶈兘浣庝簬 60%銆?- 鑷冲皯闇€瑕?3 娆＄湡瀹炴暟鎹€欓€夌瓥鐣ュ垎琛屾儏楠岃瘉瑙傚療銆?- 鑷冲皯闇€瑕?1 娆＄湡瀹炴暟鎹€欓€夌瓥鐣ュ垎琛屾儏楠岃瘉 PASS銆?- 鏅嬬骇鍓嶅繀椤昏杩?defensive 鎴?risk_off 绐楀彛,閬垮厤鍙湪椤洪琛屾儏閲岃瘎浼扮瓥鐣ャ€?- 鐪熷疄鏁版嵁骞冲潎鍥炴挙鍜屾嫆鍗曠巼蹇呴』浣庝簬棰勭畻銆?
婊¤冻杩欎簺鏉′欢涔熷彧琛ㄧず鍙互杩涘叆鏇存繁鍏ョ殑 paper-stage review,浠嶇劧涓嶆槸瀹炵洏鎸囦护銆?
## 鏅嬬骇瀹℃煡

瀵归暱鏈?registry 鍋氳祫閲戠洰鏍囧鏌?

```powershell
uv run python examples/review_strategy_promotions.py --registry results/strategy_registry/strategy_registry.json --output-dir results/strategy_registry --starting-capital 100000 --target-capital 1000000 --years 8
```

鏅嬬骇瀹℃煡浼氭鏌?

- 鐪熷疄瑙傚療娆℃暟鍜岀湡瀹?PASS 娆℃暟銆?- 鐪熷疄骞冲潎骞村寲鏀剁泭鏄惁杈惧埌璧勯噾鐩爣璺緞銆?- 鐪熷疄骞冲潎鍥炴挙鏄惁浣庝簬棰勭畻銆?- 鐪熷疄骞冲潎澶忔櫘鏄惁杈惧埌瑙傚療绾裤€?
`PASS` 鍙〃绀哄€欓€夊彲浠ヨ繘鍏ユ洿娣卞叆鐨?paper-stage review銆傚畠涓嶅厑璁歌繛鎺?broker銆佷笉鍏佽鑷姩涓嬪崟銆佷笉鍏佽鎻愰珮璧勯噾銆?
