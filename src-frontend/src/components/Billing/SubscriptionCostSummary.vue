<template>
  <div v-if="upcoming">
    <!-- Desktop table -->
    <q-markup-table
      bordered
      flat
      class="rounded-borders desktop-only q-mb-xs full-width"
    >
      <thead>
        <tr>
          <th class="text-left">{{ $t('paymentPlans.upcomingInvoice') }}</th>
          <th class="text-right">{{ $t('paymentPlans.totalDue') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(line, i) in upcoming.lines" :key="i">
          <td class="text-left">
            <q-badge
              :color="categoryColor(line.category)"
              class="q-mr-sm"
              style="font-size: 0.7em"
            >
              {{ $t(`paymentPlans.lineType.${line.category}`) }}
            </q-badge>
            {{ line.description }}
          </td>
          <td class="text-right">
            {{ $n(line.amount / 100, 'currency', siteLocaleCurrency) }}
          </td>
        </tr>
        <tr class="text-weight-bold">
          <td class="text-left">{{ $t('paymentPlans.totalDue') }}</td>
          <td class="text-right">
            {{ $n(upcoming.amount_due / 100, 'currency', siteLocaleCurrency) }}
          </td>
        </tr>
      </tbody>
    </q-markup-table>

    <!-- Mobile list -->
    <q-list
      bordered
      class="rounded-borders desktop-hide q-mb-xs"
      style="max-width: 350px"
    >
      <q-item v-for="(line, i) in upcoming.lines" :key="i">
        <q-item-section>
          <q-item-label>
            <q-badge
              :color="categoryColor(line.category)"
              class="q-mr-xs"
              style="font-size: 0.7em"
            >
              {{ $t(`paymentPlans.lineType.${line.category}`) }}
            </q-badge>
            {{ line.description }}
          </q-item-label>
          <q-item-label caption>
            {{ $n(line.amount / 100, 'currency', siteLocaleCurrency) }}
          </q-item-label>
        </q-item-section>
      </q-item>
      <q-item class="text-weight-bold">
        <q-item-section>
          <q-item-label>{{ $t('paymentPlans.totalDue') }}</q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-item-label>
            {{ $n(upcoming.amount_due / 100, 'currency', siteLocaleCurrency) }}
          </q-item-label>
        </q-item-section>
      </q-item>
    </q-list>

    <div class="text-caption text-grey q-mb-md">
      {{ $t('paymentPlans.billingPeriod') }}:
      {{ formatDate(upcoming.period_start) }} –
      {{ formatDate(upcoming.period_end) }}
    </div>
  </div>
</template>

<script lang="ts">
import { mapGetters } from 'vuex';

type LineCategory = 'main' | 'billing_group_addon' | 'addon' | 'proration';

const CATEGORY_COLORS: Record<LineCategory, string> = {
  main: 'primary',
  billing_group_addon: 'secondary',
  addon: 'info',
  proration: 'warning',
};

export default {
  name: 'SubscriptionCostSummary',
  data() {
    return {
      upcoming: null as null | {
        amount_due: number;
        currency: string;
        period_start: number;
        period_end: number;
        lines: {
          description: string;
          amount: number;
          category: LineCategory;
        }[];
      },
    };
  },
  computed: {
    ...mapGetters('config', ['siteLocaleCurrency']),
  },
  async mounted() {
    try {
      const result = await this.$axios.get('/api/billing/myplan/cost-summary/');
      if (result.data.success) {
        this.upcoming = result.data.upcoming;
      }
    } catch {
      // Not critical; silently fail
    }
  },
  methods: {
    formatDate(unix: number) {
      return new Date(unix * 1000).toLocaleDateString('en-au');
    },
    categoryColor(category: LineCategory): string {
      return CATEGORY_COLORS[category] ?? 'grey';
    },
  },
};
</script>
