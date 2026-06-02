import { z } from 'zod';

export const SubscriptionStateSchema = z.enum([
  'inactive',
  'active',
  'cancelling',
  'group_active',
  'group_inactive',
]);
export type SubscriptionState = z.infer<typeof SubscriptionStateSchema>;

export const SubscriptionAddonSchema = z.object({
  id: z.number(),
  name: z.string(),
  description: z.string(),
  addon_type: z.string(),
  addon_type_display: z.string(),
  visible: z.boolean(),
  currency: z.string(),
  cost: z.number(),
  cost_display: z.string(),
  interval_count: z.number(),
  interval: z.string(),
  max_quantity: z.number(),
  min_quantity: z.number(),
  stripe_synced: z.boolean(),
});
export type SubscriptionAddon = z.infer<typeof SubscriptionAddonSchema>;

export const MemberPlanSchema = z.object({
  id: z.number(),
  name: z.string(),
  currency: z.string(),
  cost: z.number(),
  intervalAmount: z.number(),
  interval: z.string(),
});

export type MemberPlan = z.infer<typeof MemberPlanSchema>;

export const MemberTierSchema = z.object({
  id: z.number(),
  name: z.string(),
  description: z.string(),
  featured: z.boolean(),
  plans: z.array(MemberPlanSchema),
});

export type MemberTier = z.infer<typeof MemberTierSchema>;

export const MemberSubscriptionSchema = z.object({
  billingCycleAnchor: z.date(),
  cancelAt: z.date(),
  cancelAtPeriodEnd: z.boolean(),
  currentPeriodEnd: z.date(),
  startDate: z.date(),
  status: z.string(),
  membershipPlan: MemberPlanSchema,
  membershipTier: MemberTierSchema,
});

export type MemberSubscription = z.infer<typeof MemberSubscriptionSchema>;
