<template>
  <div class="admin-shelf-management q-pa-md">
    <div class="row q-mb-md q-gutter-md">
      <div class="col">
        <q-input
          v-model="searchFilter"
          label="Search shelves or members"
          outlined
          dense
          @update:model-value="loadShelves"
          clearable
        >
          <template v-slot:prepend>
            <q-icon name="mdi-magnify" />
          </template>
        </q-input>
      </div>
      <div class="col-auto">
        <q-select
          v-model="sortBy"
          :options="sortOptions"
          label="Sort by"
          outlined
          dense
          @update:model-value="loadShelves"
        />
      </div>
      <div class="col-auto">
        <q-btn
          label="Create Shelf"
          color="primary"
          @click="showCreateShelfDialog = true"
        />
      </div>
    </div>

    <!-- Statistics -->
    <div class="row q-mb-md q-gutter-md">
      <q-card class="col">
        <q-card-section>
          <div class="text-h6">{{ stats.total_shelves }}</div>
          <div class="text-caption">Total Shelves</div>
        </q-card-section>
      </q-card>
      <q-card class="col">
        <q-card-section>
          <div class="text-h6 text-positive">{{ stats.available }}</div>
          <div class="text-caption">Available</div>
        </q-card-section>
      </q-card>
      <q-card class="col">
        <q-card-section>
          <div class="text-h6 text-primary">{{ stats.occupied }}</div>
          <div class="text-caption">Occupied</div>
        </q-card-section>
      </q-card>
      <q-card class="col">
        <q-card-section>
          <div class="text-h6 text-warning">{{ stats.pending_requests }}</div>
          <div class="text-caption">Pending Requests</div>
        </q-card-section>
      </q-card>
    </div>

    <div class="row q-col-gutter-md">
      <!-- Shelves List -->
      <div class="col-12 col-md-8">
        <q-card>
          <q-card-section>
            <div class="text-h6">Shelves</div>
          </q-card-section>

          <q-card-section>
            <q-table
              :rows="shelves"
              :columns="shelfColumns"
              row-key="id"
              :loading="loading"
              flat
              bordered
              :pagination="{ rowsPerPage: 20 }"
            >
              <template v-slot:body-cell-status="props">
                <q-td :props="props">
                  <q-chip
                    :color="getStatusColor(props.row.status)"
                    text-color="white"
                    size="sm"
                  >
                    {{ props.row.status_display }}
                  </q-chip>
                </q-td>
              </template>

              <template v-slot:body-cell-current_member="props">
                <q-td :props="props">
                  <div v-if="props.row.current_member">
                    {{ props.row.current_member.fullName }}
                    <div class="text-caption text-grey-7">
                      Since {{ formatDate(props.row.start_date) }}
                    </div>
                  </div>
                  <span v-else class="text-grey-6">—</span>
                </q-td>
              </template>

              <template v-slot:body-cell-next_member="props">
                <q-td :props="props">
                  <div v-if="props.row.next_member">
                    {{ props.row.next_member.fullName }}
                    <div class="text-caption text-grey-7">
                      From {{ formatDate(props.row.next_available_date) }}
                    </div>
                  </div>
                  <span v-else class="text-grey-6">—</span>
                </q-td>
              </template>

              <template v-slot:body-cell-actions="props">
                <q-td :props="props">
                  <q-btn-dropdown
                    color="primary"
                    label="Actions"
                    size="sm"
                    flat
                  >
                    <q-list>
                      <q-item
                        v-if="!props.row.current_member"
                        clickable
                        v-close-popup
                        @click="openAssignDialog(props.row, false)"
                      >
                        <q-item-section>
                          <q-item-label>Assign Member</q-item-label>
                        </q-item-section>
                      </q-item>

                      <q-item
                        v-if="props.row.current_member"
                        clickable
                        v-close-popup
                        @click="removeMember(props.row, 'current')"
                      >
                        <q-item-section>
                          <q-item-label>Remove Current Member</q-item-label>
                        </q-item-section>
                      </q-item>

                      <q-item
                        v-if="
                          props.row.current_member && !props.row.next_member
                        "
                        clickable
                        v-close-popup
                        @click="openAssignDialog(props.row, true)"
                      >
                        <q-item-section>
                          <q-item-label>Assign Next Occupant</q-item-label>
                        </q-item-section>
                      </q-item>

                      <q-item
                        v-if="props.row.next_member"
                        clickable
                        v-close-popup
                        @click="removeMember(props.row, 'next')"
                      >
                        <q-item-section>
                          <q-item-label>Remove Next Occupant</q-item-label>
                        </q-item-section>
                      </q-item>
                    </q-list>
                  </q-btn-dropdown>
                </q-td>
              </template>
            </q-table>
          </q-card-section>
        </q-card>
      </div>

      <!-- Request Queue -->
      <div class="col-12 col-md-4">
        <q-card>
          <q-card-section>
            <div class="text-h6">Request Queue</div>
            <div class="text-caption text-grey-7">
              {{ queue.length }} pending request(s)
            </div>
          </q-card-section>

          <q-card-section>
            <q-list bordered separator>
              <q-item v-for="request in queue" :key="request.id">
                <q-item-section>
                  <q-item-label>{{ request.member.name }}</q-item-label>
                  <q-item-label caption>{{
                    request.member.email
                  }}</q-item-label>
                  <q-item-label caption class="q-mt-xs">
                    Requested {{ formatDate(request.requested_at) }}
                  </q-item-label>
                </q-item-section>

                <q-item-section side>
                  <q-btn
                    icon="mdi-account-plus"
                    color="primary"
                    size="sm"
                    round
                    flat
                    @click="openAssignDialogForRequest(request)"
                  >
                    <q-tooltip>Assign to shelf</q-tooltip>
                  </q-btn>
                </q-item-section>
              </q-item>

              <q-item v-if="queue.length === 0">
                <q-item-section>
                  <q-item-label class="text-grey-6 text-center">
                    No pending requests
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <!-- Create Shelf Dialog -->
    <q-dialog v-model="showCreateShelfDialog" persistent>
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">Create New Shelf</div>
        </q-card-section>

        <q-card-section>
          <q-form @submit="createShelf" class="q-gutter-md">
            <q-input
              v-model="createShelfForm.number"
              label="Shelf Number"
              outlined
              dense
              :rules="[(val) => !!val || 'Shelf number is required']"
            />

            <div class="row justify-end q-gutter-sm">
              <q-btn
                label="Cancel"
                color="grey"
                @click="showCreateShelfDialog = false"
                flat
              />
              <q-btn
                label="Create"
                type="submit"
                color="primary"
                :loading="loading"
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- Assign Member Dialog -->
    <q-dialog v-model="showAssignDialog" persistent>
      <q-card style="min-width: 500px">
        <q-card-section>
          <div class="text-h6">
            Assign Member to Shelf{{
              selectedShelf ? ' ' + selectedShelf.number : ''
            }}
          </div>
          <div class="text-caption text-grey-7">
            {{
              isNextOccupant
                ? 'Assigning as next occupant'
                : 'Assigning as current occupant'
            }}
          </div>
        </q-card-section>

        <q-card-section>
          <q-form @submit="assignMember" class="q-gutter-md">
            <!-- Member Search/Select -->
            <div v-if="preselectedRequest">
              <q-banner class="bg-blue-1">
                <template v-slot:avatar>
                  <q-icon name="mdi-information" color="primary" />
                </template>
                <div class="text-subtitle2">From Queue</div>
                <div class="text-body2">
                  {{ preselectedRequest.member.name }} ({{
                    preselectedRequest.member.email
                  }})
                </div>
              </q-banner>
              <q-btn
                label="Search for different member"
                color="primary"
                flat
                size="sm"
                class="q-mt-sm"
                @click="clearPreselectedRequest"
              />
            </div>

            <q-select
              v-else
              v-model="assignForm.selectedMember"
              :options="memberSearchResults"
              option-label="name"
              option-value="id"
              label="Search for member"
              outlined
              dense
              use-input
              @filter="searchMembers"
              :rules="[(val) => !!val || 'Member is required']"
            >
              <template v-slot:no-option>
                <q-item>
                  <q-item-section class="text-grey">
                    Type to search for members...
                  </q-item-section>
                </q-item>
              </template>

              <template v-slot:option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section>
                    <q-item-label>{{ scope.opt.name }}</q-item-label>
                    <q-item-label caption>{{ scope.opt.email }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>

            <!-- Shelf Selection (shown when assigning from queue) -->
            <q-select
              v-if="!selectedShelf"
              v-model="assignForm.selectedShelf"
              :options="availableShelves"
              option-label="label"
              option-value="id"
              label="Select Shelf"
              outlined
              dense
              :rules="[(val) => !!val || 'Shelf is required']"
            >
              <template v-slot:option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section>
                    <q-item-label>Shelf {{ scope.opt.number }}</q-item-label>
                    <q-item-label caption>{{
                      scope.opt.status_display
                    }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>

            <!-- Available Date -->
            <q-input
              v-model="assignForm.availableDate"
              label="Available Date"
              type="date"
              outlined
              dense
              :rules="[(val) => !!val || 'Available date is required']"
            />

            <div class="row justify-end q-gutter-sm">
              <q-btn
                label="Cancel"
                color="grey"
                @click="closeAssignDialog"
                flat
              />
              <q-btn
                label="Assign"
                type="submit"
                color="primary"
                :loading="loading"
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script>
import { format } from 'date-fns';

export default {
  name: 'AdminShelfManagement',
  data() {
    return {
      loading: false,
      searchFilter: '',
      sortBy: 'number',
      sortOptions: [
        { label: 'Shelf Number', value: 'number' },
        { label: 'Status', value: 'status' },
        { label: 'Member Name', value: 'member' },
      ],
      shelves: [],
      queue: [],
      stats: {
        total_shelves: 0,
        available: 0,
        occupied: 0,
        cancelled: 0,
        pending_requests: 0,
      },
      shelfColumns: [
        {
          name: 'number',
          label: 'Shelf #',
          field: 'number',
          align: 'left',
          sortable: true,
        },
        {
          name: 'status',
          label: 'Status',
          field: 'status',
          align: 'center',
        },
        {
          name: 'current_member',
          label: 'Current Member',
          field: 'current_member',
          align: 'left',
        },
        {
          name: 'next_member',
          label: 'Next Occupant',
          field: 'next_member',
          align: 'left',
        },
        {
          name: 'actions',
          label: 'Actions',
          field: 'actions',
          align: 'center',
        },
      ],
      showCreateShelfDialog: false,
      createShelfForm: {
        number: '',
      },
      showAssignDialog: false,
      selectedShelf: null,
      isNextOccupant: false,
      preselectedRequest: null,
      assignForm: {
        selectedMember: null,
        selectedShelf: null,
        availableDate: format(new Date(), 'yyyy-MM-dd'),
      },
      memberSearchResults: [],
      searchDebounceTimer: null,
    };
  },
  computed: {
    availableShelves() {
      // Only show shelves with status "available"
      return this.shelves
        .filter((shelf) => shelf.status === 'available')
        .map((shelf) => ({
          ...shelf,
          label: `Shelf ${shelf.number}`,
        }));
    },
  },
  methods: {
    async loadShelves() {
      this.loading = true;
      try {
        const params = {
          filter: this.searchFilter,
          sort: this.sortBy,
        };
        const response = await this.$axios.get(
          '/api/shelf-rental/admin/shelves/',
          { params }
        );

        if (response.data.success) {
          this.shelves = response.data.shelves;
          this.queue = response.data.queue;
          this.stats = response.data.stats;
        }
      } catch (error) {
        this.$q.notify({
          type: 'negative',
          message: 'Error loading shelf data',
        });
      } finally {
        this.loading = false;
      }
    },

    async createShelf() {
      this.loading = true;
      try {
        const response = await this.$axios.post(
          '/api/shelf-rental/admin/shelves/',
          {
            action: 'create_shelf',
            shelf_number: this.createShelfForm.number,
          }
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: response.data.message,
          });
          this.showCreateShelfDialog = false;
          this.createShelfForm.number = '';
          await this.loadShelves();
        }
      } catch (error) {
        this.$q.notify({
          type: 'negative',
          message: error.response?.data?.message || 'Error creating shelf',
        });
      } finally {
        this.loading = false;
      }
    },

    openAssignDialog(shelf, isNext) {
      this.selectedShelf = shelf;
      this.isNextOccupant = isNext;
      this.showAssignDialog = true;
      this.assignForm.availableDate = format(new Date(), 'yyyy-MM-dd');
    },

    openAssignDialogForRequest(request) {
      this.preselectedRequest = request;
      this.selectedShelf = null; // Will be selected in the assignment process
      this.isNextOccupant = false;
      this.showAssignDialog = true;
      this.assignForm.availableDate = format(new Date(), 'yyyy-MM-dd');
    },

    clearPreselectedRequest() {
      this.preselectedRequest = null;
    },

    closeAssignDialog() {
      this.showAssignDialog = false;
      this.selectedShelf = null;
      this.isNextOccupant = false;
      this.preselectedRequest = null;
      this.assignForm.selectedMember = null;
      this.assignForm.selectedShelf = null;
      this.memberSearchResults = [];
    },

    async searchMembers(val, update) {
      if (this.searchDebounceTimer) {
        clearTimeout(this.searchDebounceTimer);
      }

      this.searchDebounceTimer = setTimeout(async () => {
        if (val.length < 2) {
          update(() => {
            this.memberSearchResults = [];
          });
          return;
        }

        try {
          const response = await this.$axios.get(
            '/api/shelf-rental/admin/members/search/',
            {
              params: { q: val },
            }
          );

          update(() => {
            this.memberSearchResults = response.data.members;
          });
        } catch (error) {
          update(() => {
            this.memberSearchResults = [];
          });
        }
      }, 300);
    },

    async assignMember() {
      this.loading = true;
      try {
        let memberId;
        let requestId = null;
        let shelfId;

        if (this.preselectedRequest) {
          memberId = this.preselectedRequest.member.id;
          requestId = this.preselectedRequest.id;
        } else if (this.assignForm.selectedMember) {
          memberId = this.assignForm.selectedMember.id;
        } else {
          throw new Error('No member selected');
        }

        // Get shelf ID from either selectedShelf (when assigning from shelf list)
        // or from assignForm.selectedShelf (when assigning from queue)
        if (this.selectedShelf) {
          shelfId = this.selectedShelf.id;
        } else if (this.assignForm.selectedShelf) {
          shelfId = this.assignForm.selectedShelf.id;
        } else {
          throw new Error('No shelf selected');
        }

        const response = await this.$axios.post(
          '/api/shelf-rental/admin/shelves/',
          {
            action: 'assign_member',
            shelf_id: shelfId,
            member_id: memberId,
            request_id: requestId,
            available_date: this.assignForm.availableDate,
            is_next_occupant: this.isNextOccupant,
          }
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: response.data.message,
          });
          this.closeAssignDialog();
          await this.loadShelves();
        }
      } catch (error) {
        this.$q.notify({
          type: 'negative',
          message: error.response?.data?.message || 'Error assigning member',
        });
      } finally {
        this.loading = false;
      }
    },

    async removeMember(shelf, removeType) {
      const memberName =
        removeType === 'current'
          ? shelf.current_member?.fullName
          : shelf.next_member?.fullName;

      this.$q
        .dialog({
          title: 'Confirm Removal',
          message: `Are you sure you want to remove ${memberName} from Shelf ${shelf.number}?`,
          cancel: true,
          persistent: true,
        })
        .onOk(async () => {
          this.loading = true;
          try {
            const response = await this.$axios.delete(
              '/api/shelf-rental/admin/shelves/',
              {
                data: {
                  shelf_id: shelf.id,
                  remove_type: removeType,
                },
              }
            );

            if (response.data.success) {
              this.$q.notify({
                type: 'positive',
                message: response.data.message,
              });
              await this.loadShelves();
            }
          } catch (error) {
            this.$q.notify({
              type: 'negative',
              message: error.response?.data?.message || 'Error removing member',
            });
          } finally {
            this.loading = false;
          }
        });
    },

    getStatusColor(status) {
      switch (status) {
        case 'available':
          return 'positive';
        case 'occupied':
          return 'primary';
        case 'cancelled':
          return 'warning';
        default:
          return 'grey';
      }
    },

    formatDate(dateString) {
      if (!dateString) return '';
      return format(new Date(dateString), 'MMM d, yyyy');
    },
  },
  mounted() {
    this.loadShelves();
  },
};
</script>

<style scoped>
.admin-shelf-management {
  max-width: 1400px;
  margin: 0 auto;
}
</style>
