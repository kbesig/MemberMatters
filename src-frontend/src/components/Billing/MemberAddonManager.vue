<template>
  <div>
    <div v-if="loading">
      <q-spinner size="2em" />
    </div>

    <template v-else>
      <!-- Active addons on subscription -->
      <div class="text-subtitle2 q-mb-sm">{{ $t('addons.activeAddons') }}</div>
      <div
        v-if="activeAddons.length === 0"
        class="text-caption text-grey q-mb-md"
      >
        {{ $t('addons.noActiveAddons') }}
      </div>
      <q-list v-else dense class="q-mb-md">
        <q-item v-for="addon in activeAddons" :key="addon.id">
          <q-item-section>
            <q-item-label>{{ addon.name }}</q-item-label>
            <q-item-label caption
              >{{ addon.cost_display }} / {{ addon.interval_count }}
              {{ addon.interval }}</q-item-label
            >
          </q-item-section>
          <q-item-section side>
            <q-btn
              flat
              dense
              size="sm"
              color="negative"
              :label="$t('addons.removeFromSubscription')"
              :loading="loadingAddon === addon.id"
              @click="manageAddon(addon, 'remove')"
            />
          </q-item-section>
        </q-item>
      </q-list>

      <!-- Available addons -->
      <template v-if="availableAddons.length">
        <div class="text-subtitle2 q-mb-sm">
          {{ $t('addons.availableAddons') }}
        </div>
        <q-list dense>
          <q-item v-for="addon in availableAddons" :key="addon.id">
            <q-item-section>
              <q-item-label>{{ addon.name }}</q-item-label>
              <q-item-label caption
                >{{ addon.cost_display }} / {{ addon.interval_count }}
                {{ addon.interval }}</q-item-label
              >
              <q-item-label caption v-if="addon.description">{{
                addon.description
              }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn
                flat
                dense
                size="sm"
                color="primary"
                :label="$t('addons.addToSubscription')"
                :loading="loadingAddon === addon.id"
                @click="manageAddon(addon, 'add')"
              />
            </q-item-section>
          </q-item>
        </q-list>
      </template>
    </template>
  </div>
</template>

<script lang="ts">
export default {
  name: 'MemberAddonManager',
  data() {
    return {
      loading: true,
      allAddons: [] as {
        id: number;
        name: string;
        description: string;
        cost: number;
        cost_display: string;
        interval: string;
        interval_count: number;
        active?: boolean;
      }[],
      activeAddonIds: [] as number[],
      loadingAddon: null as null | number,
    };
  },
  computed: {
    activeAddons() {
      return this.allAddons.filter((a) => this.activeAddonIds.includes(a.id));
    },
    availableAddons() {
      return this.allAddons.filter((a) => !this.activeAddonIds.includes(a.id));
    },
  },
  async mounted() {
    await this.fetchAddons();
  },
  methods: {
    async fetchAddons() {
      this.loading = true;
      try {
        const result = await this.$axios.get('/api/billing/addons/');
        this.allAddons = Array.isArray(result.data.addons)
          ? result.data.addons
          : Array.isArray(result.data)
          ? result.data
          : [];
        this.activeAddonIds = Array.isArray(result.data.activeAddonIds)
          ? result.data.activeAddonIds
          : [];
      } catch {
        this.allAddons = [];
      } finally {
        this.loading = false;
      }
    },
    async manageAddon(
      addon: (typeof this.allAddons)[0],
      action: 'add' | 'remove'
    ) {
      this.loadingAddon = addon.id;
      try {
        const result = await this.$axios.post('/api/billing/addons/manage/', {
          addon_id: addon.id,
          action,
          quantity: 1,
        });
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t(
              action === 'add' ? 'addons.addSuccess' : 'addons.removeSuccess'
            ),
          });
          await this.fetchAddons();
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t(
              action === 'add' ? 'addons.addFailed' : 'addons.removeFailed'
            ),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t(
            action === 'add' ? 'addons.addFailed' : 'addons.removeFailed'
          ),
        });
      } finally {
        this.loadingAddon = null;
      }
    },
  },
};
</script>
