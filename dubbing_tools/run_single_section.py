"""
【非推奨】このスクリプトは run_batch.py に統合されました。

  python dubbing_tools/run_batch.py

を実行してください。引数なしで起動すると、全セクション一括処理か
単一セクション選択かを対話式で選べます。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

print("⚠️  run_single_section.py は run_batch.py に統合されました。")
print("   python dubbing_tools/run_batch.py を実行してください。")

from dubbing_tools.run_batch import main  # noqa: E402

sys.exit(main())
