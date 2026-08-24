<template>
  <div>
    <q-spinner v-if="loading" size="2em" />

    <template v-else>
      <!-- Not configured -->
      <div v-if="!configured" class="text-caption text-grey">
        {{ $t('shelfRental.notConfigured') }}
      </div>

      <template v-else>
        <!-- Current shelves -->
        <div class="text-subtitle2 q-mb-sm">
          {{ $t('shelfRental.myShelves') }}
        </div>
        <div v-if="shelves.length === 0" class="text-caption text-grey q-mb-md">
          {{ $t('shelfRental.noShelves') }}
        </div>
        <q-list v-else dense class="q-mb-md">
          <q-item v-for="shelf in shelves" :key="shelf.id">
            <q-item-section>
              <q-item-label>
                {{ $t('shelfRental.shelfNumber') }}: {{ shelf.number }}
              </q-item-label>
              <q-item-label caption v-if="shelf.start_date">
                {{ $t('shelfRental.startDate') }}: {{ shelf.start_date }}
              </q-item-label>
              <q-item-label caption v-if="shelf.pricing">
                {{ shelf.pricing.cost_display }} / {{ shelf.pricing.interval }}
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>

        <!-- Pending requests -->
        <div class="text-subtitle2 q-mb-sm">
          {{ $t('shelfRental.pendingRequests') }}
        </div>
        <div
          v-if="pendingRequests.length === 0"
          class="text-caption text-grey q-mb-md"
        >
          {{ $t('shelfRental.noPendingRequests') }}
        </div>
        <q-list v-else dense class="q-mb-md">
          <q-item v-for="req in pendingRequests" :key="req.id">
            <q-item-section>
              <q-item-label>
                {{ $t('shelfRental.quantity') }}: {{ req.quantity }}
              </q-item-label>
              <q-item-label caption>
                {{ $t('shelfRental.requestedAt') }}:
                {{ formatDate(req.requested_at) }}
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn
                flat
                dense
                size="sm"
                color="negative"
                :label="$t('shelfRental.cancelRequest')"
                :loading="loadingCancel === req.id"
                @click="cancelRequest(req)"
              />
            </q-item-section>
          </q-item>
        </q-list>

        <!-- Request new shelf -->
        <q-btn
          color="primary"
          :label="$t('shelfRental.requestShelf')"
          :loading="loadingRequest"
          @click="requestShelf"
        />
      </template>
    </template>
  </div>
</template>

<script lang="ts">
export default {
  name: 'ShelfRentalManager',
  data() {
    return {
      loading: true,
      configured: false,
      shelves: [] as {
        id: number;
        number: string;
        status: string;
        start_date: string | null;
        pricing: { cost_display: string; interval: string } | null;
      }[],
      pendingRequests: [] as {
        id: number;
        quantity: number;
        status: string;
        requested_at: string;
      }[],
      loadingRequest: false,
      loadingCancel: null as null | number,
    };
  },
  async mounted() {
    await this.fetchShelves();
  },
  methods: {
    formatDate(dateStr: string) {
      return new Date(dateStr).toLocaleDateString('en-au');
    },
    async fetchShelves() {
      this.loading = true;
      try {
        const result = await this.$axios.get('/api/shelf-rental/my-shelves/');
        this.configured = true;
        this.shelves = result.data.shelves || [];
        this.pendingRequests = (result.data.pending_requests || []).filter(
          (r: { status: string }) => r.status === 'pending'
        );
      } catch (err: unknown) {
        // 404 or not configured
        this.configured = false;
        this.shelves = [];
        this.pendingRequests = [];
      } finally {
        this.loading = false;
      }
    },
    async requestShelf() {
      this.loadingRequest = true;
      try {
        const result = await this.$axios.post('/api/shelf-rental/my-shelves/', {
          quantity: 1,
        });
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('shelfRental.requestSuccess'),
          });
          await this.fetchShelves();
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t('shelfRental.requestFailed'),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('shelfRental.requestFailed'),
        });
      } finally {
        this.loadingRequest = false;
      }
    },
    async cancelRequest(req: (typeof this.pendingRequests)[0]) {
      this.loadingCancel = req.id;
      try {
        const result = await this.$axios.delete(
          '/api/shelf-rental/my-shelves/',
          {
            data: { request_id: req.id },
          }
        );
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('shelfRental.cancelRequestSuccess'),
          });
          await this.fetchShelves();
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t('shelfRental.cancelRequestFailed'),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('shelfRental.cancelRequestFailed'),
        });
      } finally {
        this.loadingCancel = null;
      }
    },
  },
};
</script>
