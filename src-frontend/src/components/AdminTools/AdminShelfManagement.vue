<template>
  <div>
    <!-- Stats bar -->
    <div v-if="stats" class="row q-gutter-md q-mb-md">
      <q-chip color="grey" text-color="white" icon="mdi-bookshelf">
        {{ $t('shelfRental.total') }}: {{ stats.total }}
      </q-chip>
      <q-chip color="positive" text-color="white" icon="mdi-account">
        {{ $t('shelfRental.occupied') }}: {{ stats.occupied }}
      </q-chip>
      <q-chip color="primary" text-color="white" icon="mdi-check">
        {{ $t('shelfRental.available') }}: {{ stats.available }}
      </q-chip>
    </div>

    <div class="row q-gutter-md">
      <!-- Shelves table -->
      <div class="col">
        <div class="row justify-between items-center q-mb-sm">
          <div class="text-subtitle1">
            {{ $t('shelfRental.manageShelves') }}
          </div>
          <q-btn
            color="primary"
            size="sm"
            :icon="icons.add"
            :label="$t('shelfRental.createShelf')"
            @click="openCreateShelf"
          />
        </div>

        <q-table
          :rows="shelves"
          :columns="shelfColumns"
          :no-data-label="$t('error.noData')"
          :loading="loading"
          row-key="id"
          :filter="filter"
          dense
        >
          <template v-slot:top-right>
            <q-input
              v-model="filter"
              outlined
              dense
              debounce="300"
              placeholder="Search"
            >
              <template v-slot:append>
                <q-icon :name="icons.search" />
              </template>
            </q-input>
          </template>

          <template v-slot:body-cell-status="props">
            <q-td :props="props">
              <q-chip
                dense
                :color="statusColor(props.row.status)"
                text-color="white"
                size="sm"
              >
                {{ $t(`shelfRental.status${capitalize(props.row.status)}`) }}
              </q-chip>
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <template v-if="props.row.status === 'available'">
                <q-btn
                  flat
                  round
                  dense
                  size="sm"
                  icon="mdi-account-plus"
                  :title="$t('shelfRental.assignMember')"
                  @click.stop="openAssignDialog(props.row)"
                />
              </template>
              <template v-else-if="props.row.status === 'occupied'">
                <q-btn
                  flat
                  round
                  dense
                  size="sm"
                  icon="mdi-account-arrow-right"
                  :title="$t('shelfRental.setNextMember')"
                  @click.stop="openSetNextDialog(props.row)"
                />
                <q-btn
                  flat
                  round
                  dense
                  size="sm"
                  color="negative"
                  icon="mdi-account-remove"
                  :title="$t('shelfRental.removeMember')"
                  @click.stop="removeMember(props.row)"
                />
              </template>
            </q-td>
          </template>
        </q-table>
      </div>

      <!-- Request queue -->
      <div class="col-12 col-md-4">
        <div class="text-subtitle1 q-mb-sm">
          {{ $t('shelfRental.requestQueue') }}
        </div>
        <q-list dense bordered>
          <q-item v-if="queue.length === 0">
            <q-item-section>
              <q-item-label class="text-grey">{{
                $t('shelfRental.noRequests')
              }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-item v-for="req in queue" :key="req.id">
            <q-item-section>
              <q-item-label>{{ req.member.name }}</q-item-label>
              <q-item-label caption>
                {{ $t('shelfRental.quantity') }}: {{ req.quantity }} ·
                {{ formatDate(req.requested_at) }}
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn
                flat
                dense
                size="sm"
                color="primary"
                icon="mdi-bookshelf"
                :title="$t('shelfRental.assignMember')"
                @click="openAssignFromQueue(req)"
              />
            </q-item-section>
          </q-item>
        </q-list>
      </div>
    </div>

    <!-- Create shelf dialog -->
    <q-dialog v-model="showCreateShelf">
      <q-card style="min-width: 300px">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">{{ $t('shelfRental.createShelf') }}</div>
          <q-space />
          <q-btn icon="mdi-close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <q-input
            v-model="newShelfNumber"
            :label="$t('shelfRental.shelfNumber')"
            outlined
            autofocus
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('button.cancel')" v-close-popup />
          <q-btn
            color="primary"
            :label="$t('shelfRental.createShelf')"
            :loading="loadingCreate"
            :disable="!newShelfNumber.trim()"
            @click="createShelf"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Assign member dialog -->
    <q-dialog v-model="showAssign">
      <q-card style="min-width: 400px">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">
            {{ $t('shelfRental.assignMember') }}
            <span v-if="assigningShelf"> — {{ assigningShelf.number }}</span>
          </div>
          <q-space />
          <q-btn icon="mdi-close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <q-input
            v-model="memberSearch"
            :label="$t('shelfRental.memberSearch')"
            outlined
            debounce="300"
            @update:model-value="searchMembers"
          />
          <q-list v-if="memberResults.length" dense class="q-mt-sm">
            <q-item
              v-for="m in memberResults"
              :key="m.id"
              clickable
              @click="selectMember(m)"
              :class="{ 'bg-primary text-white': selectedMember?.id === m.id }"
            >
              <q-item-section>
                <q-item-label>{{ m.name }}</q-item-label>
                <q-item-label
                  caption
                  :class="selectedMember?.id === m.id ? 'text-white' : ''"
                >
                  {{ m.email }}
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('button.cancel')" v-close-popup />
          <q-btn
            color="primary"
            :label="$t('shelfRental.assignMember')"
            :loading="loadingAssign"
            :disable="!selectedMember"
            @click="assignMember"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Set next occupant dialog -->
    <q-dialog v-model="showSetNext">
      <q-card style="min-width: 400px">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">
            {{ $t('shelfRental.setNextMember') }}
            <span v-if="setNextShelf"> — {{ setNextShelf.number }}</span>
          </div>
          <q-space />
          <q-btn icon="mdi-close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <q-input
            v-model="nextMemberSearch"
            :label="$t('shelfRental.memberSearch')"
            outlined
            debounce="300"
            @update:model-value="searchNextMembers"
          />
          <q-list v-if="nextMemberResults.length" dense class="q-mt-sm">
            <q-item
              v-for="m in nextMemberResults"
              :key="m.id"
              clickable
              @click="selectNextMember(m)"
              :class="{
                'bg-primary text-white': selectedNextMember?.id === m.id,
              }"
            >
              <q-item-section>
                <q-item-label>{{ m.name }}</q-item-label>
                <q-item-label
                  caption
                  :class="selectedNextMember?.id === m.id ? 'text-white' : ''"
                >
                  {{ m.email }}
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('button.cancel')" v-close-popup />
          <q-btn
            color="primary"
            :label="$t('shelfRental.setNextMember')"
            :loading="loadingSetNext"
            :disable="!selectedNextMember"
            @click="setNextMember"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script lang="ts">
import icons from '@icons';

type ShelfRow = {
  id: number;
  number: string;
  status: string;
  current_member: { id: number; name: string; email: string } | null;
  next_member: { id: number; name: string } | null;
  start_date: string | null;
  next_available_date: string | null;
};

type MemberResult = { id: number; name: string; email: string };

export default {
  name: 'AdminShelfManagement',
  data() {
    return {
      loading: true,
      filter: '',
      shelves: [] as ShelfRow[],
      queue: [] as {
        id: number;
        member: { id: number; name: string };
        quantity: number;
        requested_at: string;
      }[],
      stats: null as null | {
        total: number;
        occupied: number;
        available: number;
      },
      // Create shelf
      showCreateShelf: false,
      newShelfNumber: '',
      loadingCreate: false,
      // Assign
      showAssign: false,
      assigningShelf: null as null | ShelfRow,
      memberSearch: '',
      memberResults: [] as MemberResult[],
      selectedMember: null as null | MemberResult,
      loadingAssign: false,
      // Set next
      showSetNext: false,
      setNextShelf: null as null | ShelfRow,
      nextMemberSearch: '',
      nextMemberResults: [] as MemberResult[],
      selectedNextMember: null as null | MemberResult,
      loadingSetNext: false,
    };
  },
  computed: {
    icons() {
      return icons;
    },
    shelfColumns() {
      return [
        {
          name: 'number',
          label: this.$t('shelfRental.shelfNumber'),
          field: 'number',
          sortable: true,
          align: 'left',
        },
        {
          name: 'status',
          label: this.$t('shelfRental.status'),
          field: 'status',
          sortable: true,
          align: 'left',
        },
        {
          name: 'current_member',
          label: this.$t('shelfRental.currentMember'),
          field: (row: ShelfRow) =>
            row.current_member?.name || this.$t('shelfRental.noCurrentMember'),
          align: 'left',
        },
        {
          name: 'next_member',
          label: this.$t('shelfRental.nextMember'),
          field: (row: ShelfRow) =>
            row.next_member?.name || this.$t('shelfRental.noNextMember'),
          align: 'left',
        },
        {
          name: 'start_date',
          label: this.$t('shelfRental.startDate'),
          field: 'start_date',
          align: 'left',
        },
        { name: 'actions', label: '', field: 'actions', align: 'right' },
      ];
    },
  },
  async mounted() {
    await this.fetchData();
  },
  methods: {
    capitalize(s: string) {
      return s.charAt(0).toUpperCase() + s.slice(1);
    },
    formatDate(dateStr: string) {
      return new Date(dateStr).toLocaleDateString('en-au');
    },
    statusColor(status: string) {
      const map: Record<string, string> = {
        available: 'positive',
        occupied: 'primary',
        cancelled: 'warning',
      };
      return map[status] ?? 'grey';
    },
    async fetchData() {
      this.loading = true;
      try {
        const result = await this.$axios.get(
          '/api/shelf-rental/admin/shelves/'
        );
        this.shelves = result.data.shelves || [];
        this.stats = result.data.stats || null;
        this.queue = result.data.queue || [];
      } catch {
        this.shelves = [];
        this.queue = [];
      } finally {
        this.loading = false;
      }
    },
    openCreateShelf() {
      this.newShelfNumber = '';
      this.showCreateShelf = true;
    },
    async createShelf() {
      if (!this.newShelfNumber.trim()) return;
      this.loadingCreate = true;
      try {
        const result = await this.$axios.post(
          '/api/shelf-rental/admin/shelves/',
          {
            action: 'create',
            number: this.newShelfNumber.trim(),
          }
        );
        if (result.data.success || result.data.id) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('shelfRental.createShelfSuccess'),
          });
          this.showCreateShelf = false;
          await this.fetchData();
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t('shelfRental.createShelfFailed'),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('shelfRental.createShelfFailed'),
        });
      } finally {
        this.loadingCreate = false;
      }
    },
    openAssignDialog(shelf: ShelfRow) {
      this.assigningShelf = shelf;
      this.memberSearch = '';
      this.memberResults = [];
      this.selectedMember = null;
      this.showAssign = true;
    },
    openAssignFromQueue(req: (typeof this.queue)[0]) {
      // Find an available shelf and pre-select the requesting member
      const availableShelf = this.shelves.find((s) => s.status === 'available');
      if (availableShelf) {
        this.assigningShelf = availableShelf;
        this.selectedMember = {
          id: req.member.id,
          name: req.member.name,
          email: '',
        };
        this.memberSearch = req.member.name;
        this.memberResults = [
          { id: req.member.id, name: req.member.name, email: '' },
        ];
        this.showAssign = true;
      }
    },
    async searchMembers(query: string) {
      if (!query || query.length < 2) {
        this.memberResults = [];
        return;
      }
      try {
        const result = await this.$axios.get(
          `/api/shelf-rental/admin/members/search/?q=${encodeURIComponent(
            query
          )}`
        );
        this.memberResults = Array.isArray(result.data) ? result.data : [];
      } catch {
        this.memberResults = [];
      }
    },
    selectMember(m: MemberResult) {
      this.selectedMember = m;
    },
    async assignMember() {
      if (!this.assigningShelf || !this.selectedMember) return;
      this.loadingAssign = true;
      try {
        const result = await this.$axios.post(
          '/api/shelf-rental/admin/shelves/',
          {
            action: 'assign',
            shelf_id: this.assigningShelf.id,
            member_id: this.selectedMember.id,
          }
        );
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('shelfRental.assignSuccess'),
          });
          this.showAssign = false;
          await this.fetchData();
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t('shelfRental.assignFailed'),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('shelfRental.assignFailed'),
        });
      } finally {
        this.loadingAssign = false;
      }
    },
    removeMember(shelf: ShelfRow) {
      if (!shelf.current_member) return;
      this.$q
        .dialog({
          title: this.$t('shelfRental.removeMember'),
          message: this.$t('shelfRental.removeMemberConfirm', {
            name: shelf.current_member.name,
            shelf: shelf.number,
          }),
          cancel: this.$t('button.cancel'),
          persistent: true,
        })
        .onOk(async () => {
          try {
            const result = await this.$axios.delete(
              '/api/shelf-rental/admin/shelves/',
              {
                data: {
                  shelf_id: shelf.id,
                  member_id: shelf.current_member!.id,
                },
              }
            );
            if (result.data.success) {
              this.$q.notify({
                type: 'positive',
                message: this.$t('shelfRental.removeMemberSuccess'),
              });
              await this.fetchData();
            } else {
              this.$q.notify({
                type: 'negative',
                message: this.$t('shelfRental.removeMemberFailed'),
              });
            }
          } catch {
            this.$q.notify({
              type: 'negative',
              message: this.$t('shelfRental.removeMemberFailed'),
            });
          }
        });
    },
    openSetNextDialog(shelf: ShelfRow) {
      this.setNextShelf = shelf;
      this.nextMemberSearch = '';
      this.nextMemberResults = [];
      this.selectedNextMember = null;
      this.showSetNext = true;
    },
    async searchNextMembers(query: string) {
      if (!query || query.length < 2) {
        this.nextMemberResults = [];
        return;
      }
      try {
        const result = await this.$axios.get(
          `/api/shelf-rental/admin/members/search/?q=${encodeURIComponent(
            query
          )}`
        );
        this.nextMemberResults = Array.isArray(result.data) ? result.data : [];
      } catch {
        this.nextMemberResults = [];
      }
    },
    selectNextMember(m: MemberResult) {
      this.selectedNextMember = m;
    },
    async setNextMember() {
      if (!this.setNextShelf || !this.selectedNextMember) return;
      this.loadingSetNext = true;
      try {
        const result = await this.$axios.post(
          '/api/shelf-rental/admin/shelves/',
          {
            action: 'set-next',
            shelf_id: this.setNextShelf.id,
            member_id: this.selectedNextMember.id,
          }
        );
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('shelfRental.setNextSuccess'),
          });
          this.showSetNext = false;
          await this.fetchData();
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t('shelfRental.setNextFailed'),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('shelfRental.setNextFailed'),
        });
      } finally {
        this.loadingSetNext = false;
      }
    },
  },
};
</script>
