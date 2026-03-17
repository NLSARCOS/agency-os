// components/OpportunityCard.tsx
function OpportunityCard({ opportunity }: Props) {
  const { canMove, canEdit } = useOpportunityPermissions(opportunity);
  
  return (
    <Card 
      draggable={canMove}
      className={cn(!canMove && "cursor-not-allowed opacity-75")}
    >
      {/* Content */}
      {canEdit && <QuickActions opp={opportunity} />}
    </Card>
  );
}