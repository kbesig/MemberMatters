<template>
  <div class="shelf-rental-manager q-pa-md">
    <q-card>
      <q-card-section>
        <div class="text-h5 q-mb-md">Shelf Rentals</div>
        <div class="text-body2 text-grey-7">
          Manage your shelf rental requests and current shelves
        </div>
      </q-card-section>

      <!-- Current Shelves -->
      <q-card-section v-if="currentShelves && currentShelves.length > 0">
        <div class="text-h6 q-mb-md">My Shelves</div>
        <q-list bordered separator>
          <q-item v-for="shelf in currentShelves" :key="shelf.id">
            <q-item-section avatar>
              <q-avatar color="primary" text-color="white">
                <q-icon name="mdi-shelf" />
              </q-avatar>
            </q-item-section>

            <q-item-section>
              <q-item-label>Shelf #{{ shelf.number }}</q-item-label>
              <q-item-label caption>
                <template
                  v-if="shelf.status === 'occupied' && shelf.current_member"
                >
                  <span class="text-positive">Active</span> - Since
                  {{ formatDate(shelf.start_date) }}
                </template>
                <template
                  v-else-if="shelf.status === 'cancelled' && shelf.next_member"
                >
                  <span class="text-warning">Next in Line</span> - Available
                  {{ formatDate(shelf.next_available_date) }}
                </template>
              </q-item-label>
            </q-item-section>

            <q-item-section side>
              <q-chip
                :color="shelf.status === 'occupied' ? 'positive' : 'warning'"
                text-color="white"
                size="sm"
              >
                {{ shelf.status_display }}
              </q-chip>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>

      <!-- Pending Requests -->
      <q-card-section v-if="pendingRequests && pendingRequests.length > 0">
        <div class="text-h6 q-mb-md">Pending Requests</div>
        <q-list bordered separator>
          <q-item v-for="request in pendingRequests" :key="request.id">
            <q-item-section avatar>
              <q-avatar color="warning" text-color="white">
                <q-icon name="mdi-clock-outline" />
              </q-avatar>
            </q-item-section>

            <q-item-section>
              <q-item-label>
                {{ request.quantity }} shelf{{
                  request.quantity > 1 ? 's' : ''
                }}
                requested
              </q-item-label>
              <q-item-label caption>
                Requested {{ formatDate(request.requested_at) }}
              </q-item-label>
              <q-item-label caption class="text-info q-mt-xs">
                <q-icon name="mdi-information" size="xs" class="q-mr-xs" />
                Your request is under review. You will be notified when a shelf
                is assigned.
              </q-item-label>
            </q-item-section>

            <q-item-section side>
              <q-btn
                label="Cancel"
                color="negative"
                size="sm"
                flat
                @click="cancelRequest(request.id)"
                :loading="loading"
              />
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>

      <!-- Request New Shelf -->
      <q-card-section>
        <div class="text-h6 q-mb-md">Request Shelf Rental</div>

        <div v-if="addonInfo" class="q-mb-md">
          <q-banner class="bg-blue-1">
            <template v-slot:avatar>
              <q-icon name="mdi-information" color="primary" />
            </template>
            <div class="text-subtitle2 text-weight-medium">
              {{ addonInfo.name }}
            </div>
            <div class="text-body2">
              {{ addonInfo.description }}
            </div>
            <div class="text-h6 text-primary q-mt-sm">
              {{ addonInfo.cost_display }} / {{ addonInfo.interval }}
            </div>
          </q-banner>
        </div>

        <div v-else class="q-mb-md">
          <q-banner class="bg-orange-1">
            <template v-slot:avatar>
              <q-icon name="mdi-alert" color="warning" />
            </template>
            Shelf rental is not currently configured. Please contact an
            administrator.
          </q-banner>
        </div>

        <q-form @submit="requestShelf" class="q-gutter-md">
          <q-input
            v-model.number="quantity"
            type="number"
            label="Number of Shelves"
            :rules="[
              (val) => val >= 1 || 'Must request at least 1 shelf',
              (val) =>
                val <= 10 || 'Cannot request more than 10 shelves at once',
            ]"
            outlined
            dense
            :disable="!addonInfo"
          >
            <template v-slot:prepend>
              <q-icon name="mdi-shelf" />
            </template>
          </q-input>

          <div class="row justify-end">
            <q-btn
              label="Request Shelf Rental"
              type="submit"
              color="primary"
              :loading="loading"
              :disable="!addonInfo"
            />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
  </div>
</template>

<script>
import { format } from 'date-fns';

export default {
  name: 'ShelfRentalManager',
  data() {
    return {
      loading: false,
      currentShelves: [],
      pendingRequests: [],
      addonInfo: null,
      quantity: 1,
    };
  },
  methods: {
    async loadShelfData() {
      this.loading = true;
      try {
        const response = await this.$axios.get('/api/shelf-rental/my-shelves/');
        if (response.data.success) {
          this.currentShelves = response.data.current_shelves;
          this.pendingRequests = response.data.pending_requests;
          this.addonInfo = response.data.addon_info;
        }
      } catch (error) {
        this.$q.notify({
          type: 'negative',
          message: 'Error loading shelf information',
        });
      } finally {
        this.loading = false;
      }
    },

    async requestShelf() {
      this.loading = true;
      try {
        const response = await this.$axios.post(
          '/api/shelf-rental/my-shelves/',
          {
            quantity: this.quantity,
          }
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: response.data.message,
          });
          this.quantity = 1;
          await this.loadShelfData();
        }
      } catch (error) {
        this.$q.notify({
          type: 'negative',
          message:
            error.response?.data?.message || 'Error requesting shelf rental',
        });
      } finally {
        this.loading = false;
      }
    },

    async cancelRequest(requestId) {
      this.loading = true;
      try {
        const response = await this.$axios.delete(
          '/api/shelf-rental/my-shelves/',
          {
            data: { request_id: requestId },
          }
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: response.data.message,
          });
          await this.loadShelfData();
        }
      } catch (error) {
        this.$q.notify({
          type: 'negative',
          message: error.response?.data?.message || 'Error cancelling request',
        });
      } finally {
        this.loading = false;
      }
    },

    formatDate(dateString) {
      if (!dateString) return '';
      return format(new Date(dateString), 'MMM d, yyyy');
    },
  },
  mounted() {
    this.loadShelfData();
  },
};
</script>

<style scoped>
.shelf-rental-manager {
  max-width: 900px;
  margin: 0 auto;
}
</style>
