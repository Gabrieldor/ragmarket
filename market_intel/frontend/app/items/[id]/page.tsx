import ItemDetailClient from "./ItemDetailClient";

export default async function ItemDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ItemDetailClient itemId={Number(id)} />;
}
