import { Package } from 'lucide-react'

const positions: Partial<Record<string, string>> = {
  milk: '0% 0%',
  'oat-milk': '50% 0%',
  beans: '100% 0%',
  cream: '0% 100%',
  cups: '50% 100%',
  vanilla: '100% 100%',
}

export function IngredientPhoto({ ingredientId }: { ingredientId: string }) {
  const position = positions[ingredientId]
  return (
    <span
      aria-hidden="true"
      data-ingredient-photo={position ? ingredientId : undefined}
      className="grid size-11 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground"
      style={position ? {
        backgroundImage: 'url(/ingredient-photos.webp)',
        backgroundSize: '300% 200%',
        backgroundPosition: position,
        backgroundRepeat: 'no-repeat',
      } : undefined}
    >
      {!position && <Package size={18} />}
    </span>
  )
}
