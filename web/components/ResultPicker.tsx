"use client";

export default function ResultPicker({
  options,
  value,
  onChange,
  emptyMessage,
}: {
  options: string[];
  value: string;
  onChange: (value: string) => void;
  emptyMessage: string;
}) {
  const sorted = [...options].sort();

  return (
    <div className="space-y-2">
      <div className="max-h-48 space-y-1 overflow-y-auto rounded border border-gray-200 dark:border-gray-800 p-2">
        {sorted.length === 0 && <p className="px-2 py-1 text-xs text-gray-500">{emptyMessage}</p>}
        {sorted.map((r) => {
          const selected = r === value;
          return (
            <button
              key={r}
              type="button"
              onClick={() => onChange(r)}
              className={`block w-full rounded px-2 py-1 text-left text-sm ${
                selected
                  ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
                  : "text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
              }`}
            >
              🎬 {r}
            </button>
          );
        })}
      </div>

      {value && <p className="text-xs text-gray-500">selecionado: {value}</p>}
    </div>
  );
}
